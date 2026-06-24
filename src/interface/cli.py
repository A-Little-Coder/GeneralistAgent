"""
CLI 交互模块 — 异步流式渲染、多用户/多会话切换与用户交互主循环。

设计要点：
  - **user 维度**（add-user-scope-to-memory）：启动 input 读 user_id；
    `thread_id = "{user_id}:{session_id}"`；`/user <uid>` 运行时切换 user
  - **持久化**（add-memory-persistence）：Leader 用 `LeaderStore`(AsyncSqliteSaver)
    跨进程保留对话历史，由 `SessionManager` 维护多 user × 多 session
  - **不再 rebuild_state**：每轮只把新消息 `[HumanMessage(user_input)]` 喂给
    `agent.astream`，历史由 checkpointer 自动加载与写回
  - **流式渲染**：messages 模式逐 token + updates 模式工具返回预览
  - **Session 命令**：`/new` `/sessions` `/switch` `/delete` `/title` `/user` `/help`
  - **Teammate 焚毁**：每轮 finally + `/user` 切换前都调
    `team_manager.cleanup_spawned_in_turn()`
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from src.core.agent import build_agent
from src.core.config import Config
from src.interface import log
from src.orchestration.team import TeamManager
from src.orchestration.tools import OrchestrationContext, build_orchestration_tools
from src.persistence import LeaderStore, SessionManager
from src.persistence.session_manager import DEFAULT_USER_ID
from src.skills.center import SkillCenter


# Windows 终端默认 GBK 无法显示 emoji（🛠 📥 等）—— 模块导入时即强制 UTF-8
def _ensure_utf8_stdout() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_ensure_utf8_stdout()


_BANNER = """
╔══════════════════════════════════════════════════╗
║          Generalist Agent — 供应链ChatBI          ║
║                                                  ║
║  输入 exit / quit / q 退出                         ║
║  /help 查看会话命令；技能修改 Leader 自动感知        ║
╚══════════════════════════════════════════════════╝
"""

_SYSTEM_PROMPT = """你是一个智能助手（团队 Leader）。

规则：
1. 请始终用中文回答。
2. 对于多步骤任务，先使用 write_todos 工具拆解步骤。
3. 执行过程中及时反馈进度。
4. 如果需要使用某项技能，请先 read_file 读取对应的 SKILL.md 文件了解使用方法。

# 团队能力

你已具备多 Agent 编排能力：
- 当任务需要访问外部 Agent 服务（如问数、数据查询等），**不能自己直接调用**外部服务。
- 标准工作流：
  1. team_create 建团（如已存在可复用 team_list 查到）
  2. spawn_teammate(name=..., proxy_service="<服务名>") 拉起代理 Teammate
  3. assign_task 把具体任务派给该 Teammate
  4. **wait_for_message(timeout=180)** 阻塞等回信（不要用 task_list_query 反复轮询！）
  5. 收到 task_completed 消息后汇总结果回复用户；收到 task_failed 时上报失败原因
- 你看不到代理服务的连接细节（host / token），这些由系统装配，安全。
- 可用的代理服务名见 .env 中 PROXY_<NAME>_* 配置。
- 同一请求内可以多次给同名 Teammate 派任务 / 发消息，Teammate 在请求内记得之前的对话。

# 注意
- 不要在没有相应需求时随意建团 / 拉 Teammate，避免开销。
- ⚠️ 当前运行在 Windows 系统，execute 工具不支持 `sleep`、`ping` 等命令。
  等待任务请用 wait_for_message，不要用 execute 调 sleep/wait。
- task_list_query 仅作为兜底排查使用，不要循环轮询。"""

_TOOL_RETURN_PREVIEW = 300
_TOOL_ARGS_PREVIEW = 200


# ── 流式渲染器 ───────────────────────────────────────────────────────


class StreamRenderer:
    """流式事件渲染器 —— 仅负责打印，不维护"重建用"的消息列表。"""

    def __init__(self) -> None:
        self._printed_tools: set[tuple[str, str]] = set()

    def handle(self, mode: str, data: Any) -> None:
        if mode == "messages":
            self._handle_messages(data)
        elif mode == "updates":
            self._handle_updates(data)

    def _handle_messages(self, data: Any) -> None:
        chunk, metadata = data
        node = (metadata or {}).get("langgraph_node", "")

        content = getattr(chunk, "content", None)
        if content:
            print(content, end="", flush=True)

        tool_call_chunks = getattr(chunk, "tool_call_chunks", None) or []
        for tc in tool_call_chunks:
            name = tc.get("name") if isinstance(tc, dict) else None
            if name and (node, name) not in self._printed_tools:
                self._printed_tools.add((node, name))
                print()
                log.leader_log(f"🛠 调用工具: {name}")
                args = str(tc.get("args", ""))
                if args:
                    log.leader_log(f"   参数: {args[:_TOOL_ARGS_PREVIEW]}")

    def _handle_updates(self, data: Any) -> None:
        for _node, update in (data or {}).items():
            if not isinstance(update, dict):
                continue
            msgs = update.get("messages")
            if not msgs:
                continue
            for m in msgs if isinstance(msgs, list) else [msgs]:
                if getattr(m, "type", "") == "tool":
                    preview = str(getattr(m, "content", ""))[:_TOOL_RETURN_PREVIEW]
                    print()
                    log.leader_log(f"📥 工具返回: {preview}")


async def _run_turn(agent, user_input: str, thread_id: str) -> None:
    """执行单轮流式请求。

    历史由 checkpointer 按 thread_id 自动加载；本函数仅推送新消息。
    thread_id 现为复合形式 `{user_id}:{session_id}`，由 SessionManager.compose_thread_id 拼。
    """
    renderer = StreamRenderer()
    state = {"messages": [HumanMessage(content=user_input)]}
    invoke_config = {"configurable": {"thread_id": thread_id}}
    async for mode, data in agent.astream(
        state, config=invoke_config, stream_mode=["messages", "updates"]
    ):
        renderer.handle(mode, data)
    print()  # 换行收尾


# ── 命令路由 ─────────────────────────────────────────────────────────


_COMMAND_HELP = """
会话命令：
  /new                 新建一个会话并切换为当前
  /sessions  /list     列出所有会话（标 ★ 为当前）
  /switch <序号|id>    切换到指定会话
  /delete <序号|id>    删除会话（需确认；会同步清掉历史）
  /title <新标题>      重命名当前会话
  /user <user_id>      切换当前 user（独立的 sessions 空间）
  /help  /?            显示本帮助
  exit / quit / q      退出程序
"""


def _resolve_session(sm: SessionManager, ref: str):
    """把 '序号'（从 1 开始）或 'id' 解析为 Session 对象，找不到返回 None。"""
    ref = ref.strip()
    if not ref:
        return None
    sessions = sm.list()
    try:
        idx = int(ref)
        if 1 <= idx <= len(sessions):
            return sessions[idx - 1]
    except ValueError:
        pass
    return sm.get(ref)


def _print_sessions(sm: SessionManager) -> None:
    sessions = sm.list()
    current_id = sm.current_id
    if not sessions:
        print("(无会话)")
        return
    print()
    for i, s in enumerate(sessions, 1):
        marker = "★" if s.id == current_id else " "
        title = s.title or "(未命名)"
        print(f"  {marker} [{i}] {s.id}  {title}  ({s.last_active_at})")
    print()


async def _ainput(prompt: str) -> str:
    """非阻塞 input 包装。"""
    return await asyncio.get_event_loop().run_in_executor(None, lambda: input(prompt))


async def _prompt_user_id() -> str:
    """启动时读 user_id：回车默认 'default'；含冒号拒绝重输；Ctrl+C/EOF 直接退出进程。

    add-user-scope-to-memory D1：CLI 启动唯一入口。
    """
    while True:
        try:
            raw = (await _ainput("请输入 user_id (回车默认 default): ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消启动")
            sys.exit(0)

        if raw == "":
            return DEFAULT_USER_ID
        if ":" in raw:
            print("✗ user_id 不允许包含冒号，请重新输入")
            continue
        return raw


async def _handle_command(
    line: str,
    sm: SessionManager,
    store: LeaderStore,
    team_manager: Optional[TeamManager] = None,
) -> bool:
    """处理 `/...` 命令；返回 True 表示已处理（无需走 agent 推理）。"""
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/help", "/?"):
        print(_COMMAND_HELP)
        return True

    if cmd == "/new":
        sess = sm.new()
        print(f"\n✓ 新建会话 {sess.id}（已切换）")
        return True

    if cmd in ("/sessions", "/list"):
        _print_sessions(sm)
        return True

    if cmd == "/switch":
        target = _resolve_session(sm, arg)
        if target is None:
            print(f"✗ 未找到会话 '{arg}'，可用 /sessions 查看")
            return True
        sm.switch(target.id)
        title = target.title or "(未命名)"
        print(f"\n✓ 切换到 {target.id}  {title}")
        return True

    if cmd == "/delete":
        target = _resolve_session(sm, arg)
        if target is None:
            print(f"✗ 未找到会话 '{arg}'")
            return True
        title = target.title or "(未命名)"
        confirm = (await _ainput(
            f"确定删除会话 '{target.id}'（{title}）? [y/N] "
        )).strip().lower()
        if confirm != "y":
            print("已取消删除")
            return True
        await sm.delete(target.id, leader_store=store)
        new_current = sm.get_current()
        print(f"✓ 已删除 {target.id}；当前会话 → {new_current.id if new_current else '?'}")
        return True

    if cmd == "/title":
        if not arg:
            print("用法：/title <新标题>")
            return True
        current = sm.get_current()
        if current is None:
            print("✗ 没有当前会话")
            return True
        sm.rename(current.id, arg)
        print(f"✓ 已重命名 {current.id} → {arg}")
        return True

    if cmd == "/user":
        if not arg or ":" in arg:
            print("用法：/user <user_id>（不允许包含冒号）")
            return True
        # 切 user 前先焚毁本轮已 spawn 的 Teammate —— 避免跨 user 串台
        if team_manager is not None:
            try:
                cleaned = await team_manager.cleanup_spawned_in_turn()
                if cleaned:
                    log.indent_log(f"/user 切换前 cleanup ✓ 清理 {cleaned} 个 Teammate")
            except Exception as e:
                log.indent_log(f"/user 切换前 cleanup ✗ {type(e).__name__}: {e}")

        try:
            new_uid = sm.switch_user(arg)
        except ValueError as e:
            print(f"✗ {e}")
            return True
        # 新 user 若无 session 自动 bootstrap
        sm.bootstrap()
        current = sm.get_current()
        print(
            f"\n✓ 切换到 user '{new_uid}'；"
            f"当前会话 {current.id}  {current.title or '(未命名)'}"
        )
        return True

    print(f"未知命令: {cmd}；输入 /help 查看可用命令")
    return True


# ── 主循环 ───────────────────────────────────────────────────────────


async def repl(
    model: BaseChatModel,
    skill_center: SkillCenter,
    config: Optional[Config] = None,
) -> None:
    """异步交互式主循环。

    流程：
      1. 打印 banner
      2. 启动 LeaderStore（含旧 thread_id 迁移）
      3. input 读 user_id，绑定到 SessionManager
      4. 进入 _repl_loop，每轮处理 user 输入
      5. 退出前 cleanup_all + LeaderStore.aclose
    """
    print(_BANNER)

    # ── 持久化层 ─────────────────────────────────────────────────────
    store = await LeaderStore.create()
    sm = SessionManager()

    # ── 启动绑定 user_id ─────────────────────────────────────────────
    user_id = await _prompt_user_id()
    sm.switch_user(user_id)
    current = sm.bootstrap()
    print(f"当前 user: {user_id}")
    print(f"当前会话：{current.id}  {current.title or '(未命名)'}")

    # ── 编排基础设施 ─────────────────────────────────────────────────
    team_manager = TeamManager(
        teams_root=Path(config.teams_root) if config and config.teams_root else None
    )
    orchestration_tools: list = []
    if config:
        ctx = OrchestrationContext(
            team_manager=team_manager,
            config=config,
            leader_model=model,
        )
        orchestration_tools = build_orchestration_tools(ctx)

    try:
        await _repl_loop(
            model=model,
            skill_center=skill_center,
            store=store,
            sm=sm,
            team_manager=team_manager,
            orchestration_tools=orchestration_tools,
        )
    finally:
        if config:
            try:
                await team_manager.cleanup_all()
            except Exception as e:
                print(f"\n[清理告警] cleanup_all 失败：{e}")
        try:
            await store.aclose()
        except Exception:
            pass


async def _repl_loop(
    model: BaseChatModel,
    skill_center: SkillCenter,
    store: LeaderStore,
    sm: SessionManager,
    team_manager: TeamManager,
    orchestration_tools: list,
) -> None:
    while True:
        current = sm.get_current()
        prompt_label = f"{sm.current_user_id}/{current.id}" if current else f"{sm.current_user_id}/?"
        try:
            user_input = (await _ainput(f"\n[{prompt_label}] 你 > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("\n再见！")
            break

        # 命令路由
        if user_input.startswith("/"):
            await _handle_command(user_input, sm, store, team_manager=team_manager)
            continue

        # 1. 技能变更检测（SkillCenter）
        _ = skill_center.decorate_state({})

        # 2. 标题自动填充（仅 title 为空时）
        if current is not None:
            sm.set_title_if_empty(current.id, user_input)

        # 3. 构建 Leader Agent（注入 SqliteSaver + 编排工具）
        agent = build_agent(
            model=model,
            skills_dir=skill_center.get_skills_dir(),
            system_prompt=_SYSTEM_PROMPT,
            tools=orchestration_tools or None,
            checkpointer=store.get_checkpointer(),
        )

        # 4. 流式推理（thread_id 用复合形式：user_id:session_id）
        thread_id = sm.compose_thread_id(current.id) if current else f"{sm.current_user_id}:default"
        try:
            await _run_turn(agent, user_input, thread_id)
        finally:
            # 5. 每轮焚毁本轮新建的 Teammate（X2 语义）
            try:
                cleaned = await team_manager.cleanup_spawned_in_turn()
                if cleaned:
                    log.indent_log(f"cleanup_spawned_in_turn ✓ 已清理 {cleaned} 个 Teammate")
            except Exception as e:
                log.indent_log(f"cleanup_spawned_in_turn ✗ {type(e).__name__}: {e}")
