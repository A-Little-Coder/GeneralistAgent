"""
Mailbox — 团队内 Teammate 之间的消息通道（asyncio.Queue）。

设计：
  - 每个 Teammate 拥有一个收件 Queue
  - send_message(to=name, msg) 点对点；to="*" 广播至团队所有成员
  - 读取后移除（Queue.get 语义即此）
  - 与 Claude Code 的 mailbox 等价；用 asyncio.Queue 替代 500ms 文件轮询，实时且零 CPU 空转
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Message:
    """单条消息。"""
    sender: str             # 发送者 name（"leader" 或 teammate name）
    to: str                 # 目标 name 或 "*"
    content: str            # 消息文本
    kind: str = "message"   # "message" / "shutdown_request" / "task_assigned" / ...
    meta: dict = field(default_factory=dict)


class Mailbox:
    """团队的邮箱注册中心 —— 每个 Teammate name 对应一个 Queue。

    用法：
        mb = Mailbox()
        mb.register("researcher")
        await mb.send(Message(sender="leader", to="researcher", content="开始"))
        msg = await mb.recv("researcher")   # 协程在无消息时挂起
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Message]] = {}

    # ── 注册 / 注销 ──────────────────────────────────────────────────

    def register(self, name: str) -> None:
        """为一个 Teammate 注册收件 Queue（重复注册无副作用）。"""
        self._queues.setdefault(name, asyncio.Queue())

    def unregister(self, name: str) -> None:
        """注销 Teammate 的 Queue（用于 shutdown 后清理）。"""
        self._queues.pop(name, None)

    def members(self) -> list[str]:
        return list(self._queues.keys())

    # ── 发送 ─────────────────────────────────────────────────────────

    async def send(self, msg: Message) -> int:
        """投递消息：点对点 to=name；广播 to="*" 投到除发送者外的所有成员。
        返回实际投递的份数。
        """
        if msg.to == "*":
            count = 0
            for name, q in self._queues.items():
                if name == msg.sender:
                    continue
                await q.put(msg)
                count += 1
            return count

        q = self._queues.get(msg.to)
        if q is None:
            return 0
        await q.put(msg)
        return 1

    # ── 接收 ─────────────────────────────────────────────────────────

    async def recv(self, name: str) -> Message:
        """阻塞接收一条消息（消息被读取后即从队列移除）。"""
        q = self._require(name)
        return await q.get()

    def try_recv(self, name: str) -> Optional[Message]:
        """非阻塞接收：无消息返回 None。"""
        q = self._require(name)
        try:
            return q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def pending_count(self, name: str) -> int:
        return self._require(name).qsize()

    def _require(self, name: str) -> asyncio.Queue[Message]:
        q = self._queues.get(name)
        if q is None:
            raise KeyError(f"Mailbox: 未注册的成员 '{name}'")
        return q
