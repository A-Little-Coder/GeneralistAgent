"""Trace 上下文管理模块。

本模块基于 :mod:`contextvars` 提供线程 / 协程安全的 trace 上下文，
用于在 ChatBI 的执行链路中传递与 LangSmith 关联的元数据：

    - ``user_id``：终端用户标识；
    - ``conv_id``：会话 / 对话 ID；
    - ``plan_run_id``：当前 Plan 一次运行的唯一 ID；
    - ``retry_attempt``：当前节点的重试次数（首次执行为 0）。

典型用法::

    from chatbi.observability.context import set_trace_context, trace_metadata

    with set_trace_context(user_id="u1", conv_id="c1", plan_run_id="r1"):
        # 此作用域内所有 LLM 调用、子上下文都能读到这些字段
        ...

`set_trace_context` 通过 :func:`contextlib.contextmanager` 实现，
进入时基于当前上下文做不可变拷贝再写回 ``ContextVar``，
退出时使用 ``ContextVar.reset(token)`` 精确恢复，避免污染外层栈。
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Iterator, Optional


@dataclass(frozen=True)
class TraceContext:
    """trace 上下文数据载体。

    采用 ``frozen=True`` 保证不可变，避免子作用域意外修改父作用域可见的对象。
    所有字段都给出零值默认，便于在尚未设置时安全读取。
    """

    user_id: str = ""
    conv_id: str = ""
    plan_run_id: str = ""
    retry_attempt: int = 0


# 进程级 ContextVar，默认值为空 TraceContext。
# 命名采用 ``chatbi_`` 前缀避免与第三方库冲突。
_TRACE_CTX: ContextVar[TraceContext] = ContextVar(
    "chatbi_trace_ctx", default=TraceContext()
)


def get_trace_context() -> TraceContext:
    """获取当前 trace 上下文。

    Returns:
        TraceContext: 当前协程 / 线程可见的 trace 上下文，默认是全零值。
    """

    return _TRACE_CTX.get()


@contextmanager
def set_trace_context(
    *,
    user_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    plan_run_id: Optional[str] = None,
    retry_attempt: Optional[int] = None,
) -> Iterator[TraceContext]:
    """以 ``with`` 形式临时覆盖 trace 上下文字段。

    仅覆盖显式传入的字段，未传入的字段沿用当前上下文。退出 ``with`` 块时，
    通过 ``ContextVar.reset(token)`` 精确还原，从而支持嵌套使用。

    Args:
        user_id: 用户 ID；``None`` 表示沿用当前值。
        conv_id: 会话 ID；``None`` 表示沿用当前值。
        plan_run_id: Plan 运行 ID；``None`` 表示沿用当前值。
        retry_attempt: 重试次数；``None`` 表示沿用当前值。

    Yields:
        TraceContext: 进入作用域后生效的新上下文对象。

    Example::

        with set_trace_context(user_id="u1") as ctx:
            assert ctx.user_id == "u1"
    """

    current = _TRACE_CTX.get()

    # 构造覆盖字典：仅包含显式传入（非 None）的字段。
    overrides: dict = {}
    if user_id is not None:
        overrides["user_id"] = user_id
    if conv_id is not None:
        overrides["conv_id"] = conv_id
    if plan_run_id is not None:
        overrides["plan_run_id"] = plan_run_id
    if retry_attempt is not None:
        overrides["retry_attempt"] = retry_attempt

    # frozen dataclass 通过 dataclasses.replace 生成一个新实例。
    new_ctx = replace(current, **overrides) if overrides else current
    token = _TRACE_CTX.set(new_ctx)
    try:
        yield new_ctx
    finally:
        # 精确恢复到进入前的状态，支持任意层级嵌套。
        _TRACE_CTX.reset(token)


def trace_metadata() -> dict[str, str]:
    """把当前 trace 上下文序列化为 LangSmith metadata 字典。

    LangSmith ``metadata`` 字段约定值为字符串，因此这里统一 ``str()`` 化，
    数值字段（如 ``retry_attempt``）也会被转为字符串。

    Returns:
        dict[str, str]: 字段名 -> 字符串化的值，键集合固定为
            ``{"user_id", "conv_id", "plan_run_id", "retry_attempt"}``。
    """

    ctx = _TRACE_CTX.get()
    return {
        "user_id": str(ctx.user_id),
        "conv_id": str(ctx.conv_id),
        "plan_run_id": str(ctx.plan_run_id),
        "retry_attempt": str(ctx.retry_attempt),
    }
