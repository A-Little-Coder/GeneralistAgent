"""
Teammate — 团队中的执行成员。

职责：
  - 持有独立的 TeammateContext（身份）
  - 拥有独立的 LLM 实例（可与 Leader 不同的 model/provider）
  - 装配专属工具集（如访问外部 Agent 服务的工具）
  - 通过 build_agent() 构建专属 DeepAgents Agent，注入协作 system prompt

Teammate 本身不驱动；驱动由 runner.py 的 Runner 完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from src.core.agent import build_agent
from src.orchestration.context import (
    TeammateContext,
    assign_color,
    format_agent_id,
)
from src.orchestration.proxy_tools import ProxyServiceConfig, build_proxy_tools


# 注入到 Teammate system prompt 末尾的协作指令（全中文）
_TEAMMATE_COOP_PROMPT = """

# 团队协作指令

你正在作为团队的一名成员（teammate）运行。重要规则：

1. 与团队其他成员通信，必须使用 SendMessage 工具：
   - `to: "<成员名>"` 发给特定成员
   - `to: "*"` 谨慎用于团队广播
   - 仅在文本中回复，团队其他成员看不到 —— 你必须使用 SendMessage 工具。

2. 你的工作通过"任务系统"和"成员消息"协调：
   - 共享 Task List 中可能有分配给你的任务
   - 收到的消息可能要求你完成某项工作

3. 用户主要与团队负责人（leader）交互。你完成工作后用 SendMessage 把结果发给 leader。
"""


@dataclass
class ModelConfig:
    """Teammate 独立 LLM 实例的初始化配置。

    与 src/core/config.py 的 Config 解耦：Teammate 可指定与 Leader 不同的服务商/模型。
    """
    model_name: str
    model_provider: str = "openai"
    base_url: str = ""
    api_key: str = ""

    def init(self) -> BaseChatModel:
        """构建该 Teammate 自己的 LLM 实例。"""
        kwargs = {
            "model": self.model_name,
            "model_provider": self.model_provider,
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return init_chat_model(**kwargs)


@dataclass
class Teammate:
    """团队成员：身份 + 独立模型 + 工具 + Agent 实例。"""
    name: str
    team_name: str
    model: BaseChatModel
    tools: list[BaseTool] = field(default_factory=list)
    skills_dir: Optional[str] = None
    extra_system_prompt: str = ""
    context: TeammateContext = field(init=False)

    def __post_init__(self):
        teammate_id = format_agent_id(self.name, self.team_name)
        self.context = TeammateContext(
            teammate_id=teammate_id,
            name=self.name,
            team_name=self.team_name,
            color=assign_color(teammate_id),
        )

    def build_agent_for_prompt(self, base_prompt: str = "", checkpointer=None):
        """为某次 prompt 构建该 Teammate 的 DeepAgents Agent。

        - 注入协作 system prompt
        - 装配该 Teammate 的工具集（含访问外部服务的工具）
        - 使用该 Teammate 自己的 LLM 实例
        - 可选注入 checkpointer（Runner 会传 MemorySaver 让本请求内累积记忆）；
          不传则 build_agent 内部回退到新的 MemorySaver()
        """
        system_prompt = (base_prompt or "") + (self.extra_system_prompt or "") + _TEAMMATE_COOP_PROMPT
        return build_agent(
            model=self.model,
            skills_dir=self.skills_dir,
            system_prompt=system_prompt,
            tools=self.tools or None,
            checkpointer=checkpointer,
        )


def create_teammate(
    name: str,
    team_name: str,
    model_config: Optional[ModelConfig] = None,
    fallback_model: Optional[BaseChatModel] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    skills_dir: Optional[str] = None,
    extra_system_prompt: str = "",
) -> Teammate:
    """工厂方法：根据 model_config 初始化 Teammate；未提供则使用 fallback_model。

    Args:
        name: Teammate 名（团队内唯一）。
        team_name: 所属团队。
        model_config: 独立模型配置；为 None 时必须提供 fallback_model。
        fallback_model: 当 model_config 为 None 时使用的默认模型（一般是 Leader 的模型）。
        tools: 访问外部服务的工具（仅绑定到该 Teammate）。
        skills_dir: 该 Teammate 可用的 skills 目录。
        extra_system_prompt: 额外的角色 prompt（如"你是问数代理"）。
    """
    if model_config is not None:
        model = model_config.init()
    elif fallback_model is not None:
        model = fallback_model
    else:
        raise ValueError("create_teammate: 必须提供 model_config 或 fallback_model")

    return Teammate(
        name=name,
        team_name=team_name,
        model=model,
        tools=list(tools or []),
        skills_dir=skills_dir,
        extra_system_prompt=extra_system_prompt,
    )


def create_proxy_teammate(
    name: str,
    team_name: str,
    service: ProxyServiceConfig,
    skills_root: str,
    model_config: Optional[ModelConfig] = None,
    fallback_model: Optional[BaseChatModel] = None,
    extra_system_prompt: str = "",
) -> Teammate:
    """工厂方法：为外部 Agent 服务创建代理 Teammate。

    自动完成三件事：
      1. 根据 ProxyServiceConfig 构造访问工具（HTTP / MCP）
      2. 将 skills_dir 限定到该代理 SKILL 专属子目录（skills/<skill_name>/）
      3. 注入角色 prompt（描述身份与可用工具）

    Args:
        name: Teammate 名。
        team_name: 所属团队。
        service: 外部服务配置（access_kind / base_url / auth_header 等）。
        skills_root: skills/ 父目录路径（如 Config.skills_dir）。
        model_config: 独立 LLM 配置；为 None 时需 fallback_model。
        fallback_model: 默认模型（通常是 Leader 的模型）。
        extra_system_prompt: 额外的角色 prompt，追加在 SKILL 牵引信息后方。

    Returns:
        装配好工具 + skills_dir 的 Teammate 实例。
    """
    # 1. 构造访问工具
    tools = build_proxy_tools(service)

    # 2. skills_dir 限定到代理 SKILL 子目录
    skill_name = service.resolved_skill_name()
    skill_dir = str(Path(skills_root) / skill_name)

    # 3. 角色 prompt
    role_prompt = (
        f"你是 {name}，外部 {service.name} 服务的代理 Agent。\n"
        f"你的专属 SKILL：{skill_name}\n"
        f"装配的访问工具：{[t.name for t in tools]}\n\n"
        "请先读取 SKILL.md 了解使用方式，再按约定调用工具。"
    )
    if extra_system_prompt:
        role_prompt += "\n\n" + extra_system_prompt

    if model_config is not None:
        model = model_config.init()
    elif fallback_model is not None:
        model = fallback_model
    else:
        raise ValueError("create_proxy_teammate: 必须提供 model_config 或 fallback_model")

    return Teammate(
        name=name,
        team_name=team_name,
        model=model,
        tools=tools,
        skills_dir=skill_dir,
        extra_system_prompt=role_prompt,
    )
