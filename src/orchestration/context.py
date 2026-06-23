"""
TeammateContext — 同进程多 Teammate 身份隔离（基于 contextvars）。

每个 Teammate 的 agent loop 在自己的 context 中运行：
  - get_current_teammate() 返回当前协程对应的 Teammate 身份
  - run_in_teammate_context() 包装协程使其在指定身份下运行
  - 与 Claude Code 的 teammateContext 语义等价
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar


@dataclass(frozen=True)
class TeammateContext:
    """Teammate 身份上下文（不可变）。"""
    teammate_id: str       # 唯一 ID（formatAgentId 后的结果，如 "researcher@my-team"）
    name: str              # 人类可读名，如 "researcher"
    team_name: str         # 所属团队
    color: str             # 显示色（终端 ANSI 或纯字符串标签）


# 当前协程的 TeammateContext；为 None 表示运行在 Leader 上下文
_current: contextvars.ContextVar[Optional[TeammateContext]] = contextvars.ContextVar(
    "teammate_context", default=None
)


def get_current_teammate() -> Optional[TeammateContext]:
    """返回当前协程的 Teammate 身份；Leader 上下文返回 None。"""
    return _current.get()


def is_running_as_teammate() -> bool:
    """是否运行在某个 Teammate 的上下文中。"""
    return _current.get() is not None


T = TypeVar("T")


async def run_in_teammate_context(
    ctx: TeammateContext,
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    """在指定 Teammate 上下文中运行一个协程工厂。

    使用 ContextVar.set/reset 在当前 asyncio Task 中临时切换身份；
    不会污染其他并发 Task（contextvars 与 asyncio.Task 配合做隔离）。
    """
    token = _current.set(ctx)
    try:
        return await coro_factory()
    finally:
        _current.reset(token)


# ── 身份生成辅助 ────────────────────────────────────────────────────

_PALETTE = [
    "cyan", "magenta", "green", "yellow",
    "blue", "red", "white", "bright_cyan",
]


def format_agent_id(name: str, team_name: str) -> str:
    """生成扁平 teammate_id：name@team_name。"""
    return f"{name}@{team_name}"


def assign_color(teammate_id: str) -> str:
    """按 hash 稳定分配颜色（避免重复创建同名 teammate 时跳色）。"""
    idx = abs(hash(teammate_id)) % len(_PALETTE)
    return _PALETTE[idx]
