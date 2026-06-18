"""
Agent 构建模块 — 每次请求重新实例化 DeepAgents Agent。

每次调用 build_agent() 都会创建一个全新的 Agent 实例，
确保 system prompt 中包含最新的 skill 内容。

通过 MemorySaver + thread_id 保持同一会话的上下文连续性。
"""

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend


def build_agent(
    model: BaseChatModel,
    skills_dir: str | None = None,
    system_prompt: str | None = None,
    debug: bool = False,
):
    """创建新的 DeepAgents Agent 实例。

    每次调用都重新实例化，确保技能和 prompt 为最新版本。
    使用 LocalShellBackend 同时支持文件操作和 shell 命令执行。
    """
    kwargs = dict(
        model=model,
        checkpointer=MemorySaver(),
        debug=debug,
        backend=LocalShellBackend(virtual_mode=False),
    )

    if skills_dir:
        kwargs["skills"] = [skills_dir]

    if system_prompt:
        kwargs["system_prompt"] = system_prompt

    return create_deep_agent(**kwargs)