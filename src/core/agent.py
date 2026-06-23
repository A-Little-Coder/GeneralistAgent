"""
Agent 构建模块 — 每次请求重新实例化 DeepAgents Agent。

每次调用 build_agent() 都会创建一个全新的 Agent 实例，
确保 system prompt 中包含最新的 skill 内容。

通过 MemorySaver + thread_id 保持同一会话的上下文连续性。
"""

from pathlib import Path
from typing import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver

from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend


def build_agent(
    model: BaseChatModel,
    skills_dir: str | None = None,
    system_prompt: str | None = None,
    tools: Sequence[BaseTool] | None = None,
    debug: bool = False,
):
    """创建新的 DeepAgents Agent 实例。

    每次调用都重新实例化，确保技能和 prompt 为最新版本。

    关于路径与 backend（重要 — Windows 兼容）：
      DeepAgents 的 filesystem middleware 在 read_file/write_file 等工具上强制
      调用 `validate_path()`，**拒绝 Windows 盘符开头的绝对路径**（如 `D:/...`）。
      因此当传入 `skills_dir` 时，必须用 `virtual_mode=True`，把 `skills_dir`
      的父目录作为虚拟根 `root_dir`，让 SkillsMiddleware 用虚拟路径
      `/skills/<name>/SKILL.md` 暴露给模型。
      不传 `skills_dir` 时仍保持 `virtual_mode=False`，兼容已有行为。

    Args:
        model: 该 Agent 使用的 LLM 实例（Leader 与各 Teammate 独立持有）。
        skills_dir: 本地 skills/ 目录绝对路径；其父目录将作为虚拟根。
        system_prompt: 自定义 system prompt（如 Teammate 注入协作指令）。
        tools: 额外注册的工具（如 Leader 的编排工具、Teammate 的访问工具）。
        debug: 是否输出 DeepAgents 调试信息。
    """
    if skills_dir:
        skills_path = Path(skills_dir).resolve()
        # 父目录 = 虚拟根；skills 目录在虚拟空间中表现为 /{skills 目录名}
        root_dir = skills_path.parent
        virtual_skills_path = f"/{skills_path.name}"
        backend = LocalShellBackend(root_dir=root_dir, virtual_mode=True)
        skills_arg = [virtual_skills_path]
    else:
        backend = LocalShellBackend(virtual_mode=False)
        skills_arg = None

    kwargs = dict(
        model=model,
        checkpointer=MemorySaver(),
        debug=debug,
        backend=backend,
    )

    if skills_arg is not None:
        kwargs["skills"] = skills_arg

    if system_prompt:
        kwargs["system_prompt"] = system_prompt

    if tools:
        kwargs["tools"] = list(tools)

    return create_deep_agent(**kwargs)