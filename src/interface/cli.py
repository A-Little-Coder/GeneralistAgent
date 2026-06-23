"""
CLI 交互模块 — 异步流式渲染与用户交互主循环。

设计要点（见 openspec/changes/add-agent-team-orchestration）：
  - 使用 agent.astream(stream_mode=["messages","updates"]) 真异步流式输出
  - messages 模式：逐 token 渲染 AIMessageChunk（含 tool_call_chunks）
  - updates 模式：节点边界展示工具返回，并收集完整消息用于手动重建 state
  - 流式结束后手动重建 state["messages"]（与其他 state 键 last-write-wins 合并），
    保持多轮上下文连续（因每轮 build_agent 使用全新 MemorySaver，需手动携带 state）
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel

from src.core.agent import build_agent
from src.core.config import Config
from src.interface import log
from src.orchestration.team import TeamManager
from src.orchestration.tools import OrchestrationContext, build_orchestration_tools
from src.skills.center import SkillCenter


# Windows 终端默认 GBK 无法显示 emoji（🛠 📥 等）—— 模块导入时即强制 UTF-8
# 覆盖所有走流式渲染的代码路径（REPL / Runner / ad-hoc 调用）
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
║  技能修改无需重启，自动感知最新变更                     ║
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
- 一个查询请求只需要建 **一个** Teammate，分配 **一个** 任务即可。

# 注意
- 不要在没有相应需求时随意建团 / 拉 Teammate，避免开销。
- ⚠️ 当前运行在 Windows 系统，execute 工具不支持 `sleep`、`ping` 等命令。
  等待任务请用 wait_for_message，不要用 execute 调 sleep/wait。
- task_list_query 仅作为兜底排查使用，不要循环轮询。"""

# 流式渲染时单条工具返回内容的截断长度
_TOOL_RETURN_PREVIEW = 300
# 流式渲染时工具调用参数的截断长度
_TOOL_ARGS_PREVIEW = 200


class StreamRenderer:
    """流式事件渲染器 —— 持有跨 chunk 的展示状态。

    职责：
      - messages 模式：逐 token 打印 LLM 文本与工具调用名
      - updates 模式：打印工具返回预览，并收集完整消息供 state 重建
    """

    def __init__(self) -> None:
        # 已打印过工具名的 (node, tool_name) 集合，避免重复打印
        self._printed_tools: set[tuple[str, str]] = set()
        # 收集到的完整消息（按到达顺序），用于手动重建 state
        self.collected_messages: list = []
        # 收集到的非 messages 状态键更新（last-write-wins），用于重建其他 state
        self.collected_state: dict[str, Any] = {}

    def handle(self, mode: str, data: Any) -> None:
        """处理单个流式 chunk。"""
        if mode == "messages":
            self._handle_messages(data)
        elif mode == "updates":
            self._handle_updates(data)

    # ── messages 模式：token 级渲染 ──────────────────────────────────

    def _handle_messages(self, data: Any) -> None:
        """data 形如 (chunk, metadata)。"""
        chunk, metadata = data
        node = (metadata or {}).get("langgraph_node", "")

        # 逐 token 文本输出
        content = getattr(chunk, "content", None)
        if content:
            print(content, end="", flush=True)

        # 工具调用流式片段：首个片段携带工具名
        tool_call_chunks = getattr(chunk, "tool_call_chunks", None) or []
        for tc in tool_call_chunks:
            name = tc.get("name") if isinstance(tc, dict) else None
            if name and (node, name) not in self._printed_tools:
                self._printed_tools.add((node, name))
                print()  # 换行，与前面的 token 流分隔
                log.leader_log(f"🛠 调用工具: {name}")
                args = str(tc.get("args", ""))
                if args:
                    log.leader_log(f"   参数: {args[:_TOOL_ARGS_PREVIEW]}")

    # ── updates 模式：节点边界 + 工具返回 + 消息收集 ─────────────────

    def _handle_updates(self, data: Any) -> None:
        """data 形如 {node_name: {state_key: value}}。"""
        for node, update in (data or {}).items():
            if not isinstance(update, dict):
                continue
            for key, value in update.items():
                if key == "messages":
                    msgs = value if isinstance(value, list) else [value]
                    for m in msgs:
                        self.collected_messages.append(m)
                        # 工具返回即时展示预览
                        if getattr(m, "type", "") == "tool":
                            preview = str(getattr(m, "content", ""))[:_TOOL_RETURN_PREVIEW]
                            print()  # 换行
                            log.leader_log(f"📥 工具返回: {preview}")
                else:
                    # 非 messages 键：last-write-wins（如 deepagents 的 todos）
                    self.collected_state[key] = value


def rebuild_state(input_state: dict, renderer: StreamRenderer) -> dict:
    """流式结束后手动重建完整 state。

    - messages：input_state 既有消息 + 本轮流式收集到的完整消息（AI/Tool 顺序正确）
    - 其他键（如 todos）：取 updates 中 last-write-wins 的值
    """
    new_state: dict[str, Any] = dict(input_state)
    # messages 以 input 已有历史为基础追加新消息
    base_msgs = list(new_state.get("messages", []))
    base_msgs.extend(renderer.collected_messages)
    new_state["messages"] = base_msgs
    # 合并其他状态键
    new_state.update(renderer.collected_state)
    return new_state


async def _run_turn(agent, state: dict, invoke_config: dict) -> dict:
    """执行单轮流式请求并返回重建后的 state。"""
    renderer = StreamRenderer()
    async for mode, data in agent.astream(
        state, config=invoke_config, stream_mode=["messages", "updates"]
    ):
        renderer.handle(mode, data)
    # 换行收尾，分隔本轮输出与下一轮提示符
    print()
    return rebuild_state(state, renderer)


async def repl(
    model: BaseChatModel,
    skill_center: SkillCenter,
    config: Optional[Config] = None,
) -> None:
    """异步交互式主循环。

    每次用户输入：
      1. SkillCenter 检测技能是否变更
      2. 重新实例化 Agent（确保技能和 prompt 最新，Leader 的编排工具最新）
      3. 调用 Agent.astream() 流式处理请求，逐 token 输出
      4. 手动重建 state 保持多轮上下文连续

    Args:
        model: Leader 的 LLM 实例。
        skill_center: 技能中心（检测变更 + 同步）。
        config: 可选配置项。传入了则注入团队编排工具，Leader 具备多 Agent 能力。
    """
    print(_BANNER)

    # ── 编排基础设施（可选） ───────────────────────────────────────
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

    state: dict = {"messages": []}
    invoke_config = {"configurable": {"thread_id": "generalist-agent-session"}}

    try:
        await _repl_loop(model, skill_center, state, invoke_config, orchestration_tools)
    finally:
        # 退出时清理所有 Teammate（4.4 清理钩子）
        if config:
            try:
                await team_manager.cleanup_all()
            except Exception as e:
                print(f"\n[清理告警] cleanup_all 失败：{e}")


async def _repl_loop(
    model: BaseChatModel,
    skill_center: SkillCenter,
    state: dict,
    invoke_config: dict,
    orchestration_tools: list,
) -> None:
    """REPL 主循环 —— 抽出来以便外层在 finally 中做清理。"""
    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("\n你 > ")
            )
            user_input = user_input.strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("\n再见！")
            break

        # 1. 检测技能变更，清除缓存
        state = skill_center.decorate_state(state)

        # 2. 重新实例化 Agent（注入编排工具，Leader 因此获得团队能力）
        agent = build_agent(
            model=model,
            skills_dir=skill_center.get_skills_dir(),
            system_prompt=_SYSTEM_PROMPT,
            tools=orchestration_tools or None,
        )

        # 3. 发送请求（流式）
        state["messages"].append({"role": "user", "content": user_input})
        state = await _run_turn(agent, state, invoke_config)
