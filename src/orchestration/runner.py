"""
Runner — Teammate 的执行循环（asyncio.Task）。

idle 循环（参考 Claude Code runner）：
  1. 检查 Mailbox 是否有消息（优先级最高）
     - shutdown_request → 标记 completed 退出
     - 普通消息 → 转为 prompt，运行一轮 agent loop，完成后给原 sender 投 message_reply
  2. 检查 TaskList 是否有可领任务
     - 领取成功 → 转为 prompt，运行一轮 agent loop，完成后标记 completed
                  并给 leader 投 task_completed（失败/超时投 task_failed）
  3. 都没有 → asyncio.sleep(idle_interval) 等待

每个 Teammate 一个 Runner。Runner 通过 TeammateContext 隔离身份。
通过 Mailbox 主动通知 Leader 任务完成（D9：替代 Leader 忙等 task_list_query）。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from langchain_core.messages import HumanMessage

from src.interface import log
from src.orchestration.context import run_in_teammate_context
from src.orchestration.mailbox import Mailbox, Message
from src.orchestration.task_list import TaskList
from src.orchestration.teammate import Teammate


_DEFAULT_IDLE_INTERVAL = 0.5      # idle 轮询间隔（秒）
_DEFAULT_TURN_TIMEOUT = 120.0     # 单轮 agent loop 超时（防止卡死）
_SHUTDOWN_KIND = "shutdown_request"
_TASK_KIND = "task_assigned"

# 通知 Leader 用的消息 kind 约定（与 spec.md D9 一致）
_KIND_TASK_COMPLETED = "task_completed"
_KIND_TASK_FAILED = "task_failed"
_KIND_MESSAGE_REPLY = "message_reply"


class Runner:
    """单个 Teammate 的运行循环。"""

    def __init__(
        self,
        teammate: Teammate,
        mailbox: Mailbox,
        task_list: TaskList,
        idle_interval: float = _DEFAULT_IDLE_INTERVAL,
        turn_timeout: float = _DEFAULT_TURN_TIMEOUT,
        leader_name: str = "leader",
    ):
        self._teammate = teammate
        self._mailbox = mailbox
        self._task_list = task_list
        self._idle_interval = idle_interval
        self._turn_timeout = turn_timeout
        self._leader_name = leader_name
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._last_output: str = ""           # 上一轮 agent 的最终文本（便于上层观察/测试）

    # ── 生命周期 ────────────────────────────────────────────────────

    def start(self) -> asyncio.Task:
        """启动 Runner 的 idle 循环。"""
        if self._task is not None:
            return self._task
        self._mailbox.register(self._teammate.name)
        self._task = asyncio.create_task(
            run_in_teammate_context(self._teammate.context, self._loop),
            name=f"runner-{self._teammate.context.teammate_id}",
        )
        return self._task

    async def request_shutdown(self) -> None:
        """请求 Runner 优雅退出（用 SendMessage 投递 shutdown_request 也等效）。"""
        await self._mailbox.send(Message(
            sender=self._leader_name,
            to=self._teammate.name,
            content="shutdown",
            kind=_SHUTDOWN_KIND,
        ))

    async def wait_done(self) -> None:
        """等待 Runner 退出。"""
        if self._task is not None:
            await self._task

    @property
    def last_output(self) -> str:
        return self._last_output

    # ── 主循环 ──────────────────────────────────────────────────────

    async def _loop(self) -> None:
        """idle 循环主体。退出条件：收到 shutdown_request。"""
        try:
            while not self._shutdown.is_set():
                # 1) 消息优先
                msg = self._mailbox.try_recv(self._teammate.name)
                if msg is not None:
                    if msg.kind == _SHUTDOWN_KIND:
                        self._shutdown.set()
                        break
                    await self._handle_message(msg)
                    continue

                # 2) 任务领取
                claimable = self._task_list.claimable_for(self._teammate.name)
                if claimable:
                    task = claimable[0]
                    if self._task_list.claim(task.id, self._teammate.context.teammate_id):
                        await self._handle_task(task)
                    continue

                # 3) 空闲等待
                await asyncio.sleep(self._idle_interval)
        finally:
            self._mailbox.unregister(self._teammate.name)

    # ── 消息 / 任务分支 ─────────────────────────────────────────────

    async def _handle_message(self, msg: Message) -> None:
        """处理来自 Mailbox 的普通消息，完成后回复原 sender。"""
        log.teammate_log(self._teammate.name, f"📥 收到消息 from={msg.sender}: {log.truncate(msg.content, 120)}")
        ok, result = await self._safe_run_one_turn(msg.content)
        kind = _KIND_MESSAGE_REPLY if ok else _KIND_TASK_FAILED
        await self._notify(
            to=msg.sender or self._leader_name,
            content=result,
            kind=kind,
            meta={
                "teammate_name": self._teammate.name,
                "reply_to_kind": msg.kind,
            },
        )

    async def _handle_task(self, task) -> None:
        """领取并执行任务，完成或失败后给 Leader 投递通知。"""
        log.teammate_log(self._teammate.name, f"🛠 领取任务 task_id={task.id}: {log.truncate(task.description, 120)}")
        ok, result = await self._safe_run_one_turn(task.description)
        self._task_list.complete(task.id, result=result)
        log.teammate_log(self._teammate.name, f"task {task.id} ✓ completed (ok={ok})")

        kind = _KIND_TASK_COMPLETED if ok else _KIND_TASK_FAILED
        await self._notify(
            to=self._leader_name,
            content=result,
            kind=kind,
            meta={
                "task_id": task.id,
                "teammate_name": self._teammate.name,
            },
        )

    async def _safe_run_one_turn(self, prompt: str) -> tuple[bool, str]:
        """包一层异常 + 超时捕获，返回 (success, final_text)。"""
        try:
            text = await self._run_one_turn(prompt)
            # _run_one_turn 内部捕获超时后会返回带 "[超时]" 的字符串
            if text.startswith("[超时]"):
                return False, text
            return True, text
        except Exception as e:
            text = f"[异常] {type(e).__name__}: {e}"
            self._last_output = text
            return False, text

    async def _notify(self, to: str, content: str, kind: str, meta: dict) -> None:
        """统一封装 Mailbox 投递 + 日志。"""
        log.teammate_log(
            self._teammate.name,
            f"→ {to} [{kind}] meta={log.fmt_kv(meta)}",
        )
        await self._mailbox.send(Message(
            sender=self._teammate.name,
            to=to,
            content=content,
            kind=kind,
            meta=meta,
        ))

    # ── 真实 agent 调用 ─────────────────────────────────────────────

    async def _run_one_turn(self, prompt: str) -> str:
        """运行一轮 agent loop，返回最终 AI 文本。

        每轮重新 build_agent_for_prompt —— 保证 SKILL 与工具是最新的。
        每轮从初始 prompt 构建上下文（不继承 Leader 完整对话历史）。
        设超时保护：超过 self._turn_timeout 秒则终止并返回超时提示。
        """
        agent = self._teammate.build_agent_for_prompt()
        state = {"messages": [HumanMessage(content=prompt)]}
        cfg = {"configurable": {"thread_id": self._teammate.context.teammate_id}}
        name = self._teammate.name

        async def _stream() -> str:
            t = ""
            step = 0
            async for mode, data in agent.astream(state, config=cfg, stream_mode=["updates"]):
                for node, update in (data or {}).items():
                    if not isinstance(update, dict):
                        continue
                    msgs = update.get("messages")
                    if not msgs:
                        continue
                    for m in msgs if isinstance(msgs, list) else [msgs]:
                        # ── 工具调用阶段 ────────────────────────────
                        if getattr(m, "type", "") == "ai" and getattr(m, "tool_calls", None):
                            for tc in m.tool_calls:
                                step += 1
                                log.teammate_log(
                                    name,
                                    f"step {step} 🛠 {tc['name']}({log.truncate(tc.get('args', {}), 150)})",
                                )
                        # ── 工具返回阶段 ────────────────────────────
                        if getattr(m, "type", "") == "tool":
                            step += 1
                            log.teammate_log(
                                name,
                                f"step {step} 📥 {m.name or 'tool'}: {log.truncate(getattr(m, 'content', ''), 150)}",
                            )
                        # ── AI 最终文本 ─────────────────────────────
                        if getattr(m, "type", "") == "ai" and getattr(m, "content", ""):
                            t = m.content
                        if getattr(m, "type", "") == "ai" and not getattr(m, "tool_calls", None) and getattr(m, "content", ""):
                            step += 1
                            log.teammate_log(
                                name,
                                f"step {step} 💬 回复: {log.truncate(m.content, 200)}",
                            )
            return t

        try:
            final_text = await asyncio.wait_for(_stream(), timeout=self._turn_timeout)
        except asyncio.TimeoutError:
            final_text = (
                f"[超时] Agent 执行超过 {self._turn_timeout}s，自动终止。"
                f"初始 prompt: {prompt[:200]}"
            )
            log.teammate_log(name, f"⏱ 超时 {self._turn_timeout}s 自动终止")

        self._last_output = final_text
        return final_text
