"""LLM 工厂模块。

统一提供 ChatBI 中所有 LLM 实例的构建入口，强制规约：

* 仅经由 ``langchain_openai.ChatOpenAI`` 创建（OpenAI 兼容协议），
  禁止业务代码直接 ``import openai``；
* 实例创建时立即绑定 LangSmith metadata（来自当前 trace 上下文）
  与统一的 ``run_name``，便于在 LangSmith 平台聚合检索；
* 通过 ``name`` 形参预留多模型路由扩展点，当前阶段恒返回 default。

调用方应先进入 :func:`chatbi.observability.context.set_trace_context`
作用域再调用 :func:`get_chat_model`，以便 metadata 快照携带正确的
``user_id / conv_id / plan_run_id / retry_attempt``。
"""

from __future__ import annotations

from typing import Union

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI

from chatbi.infra.config.settings import get_settings
from chatbi.observability.context import trace_metadata


def get_chat_model(
    name: str = "default", **overrides
) -> Union[Runnable, BaseChatModel]:
    """构建一个绑定了 LangSmith metadata 的 Chat LLM 实例。

    Args:
        name: 模型逻辑名（保留扩展点，当前实现忽略，恒按 default 配置返回）。
        **overrides: 透传给 :class:`langchain_openai.ChatOpenAI` 的覆盖参数，
            可覆盖任意默认字段（``model`` / ``temperature`` / ``max_tokens`` 等）。

    Returns:
        Runnable | BaseChatModel: 经 ``with_config`` 绑定后得到的
        ``RunnableBinding``（仍是 :class:`Runnable` 子类），可直接 ``invoke``、
        以及作为 LCEL 链的一部分。

    Notes:
        ``trace_metadata()`` 在本函数调用时刻取一次快照绑定到 Runnable，
        如需更细粒度的上下文（例如在循环中变化的 ``retry_attempt``），
        请在循环内重新调用 :func:`get_chat_model`，或在每次 invoke 时
        通过 ``invoke(..., config={"metadata": ...})`` 临时覆盖。
    """

    # 当前不做多模型路由：name 仅作为占位参数。
    _ = name

    settings = get_settings()

    # 默认参数集合，允许 overrides 覆盖任意字段。
    base_kwargs = {
        "api_key": settings.qwen_api_key,
        "base_url": settings.qwen_base_url,
        "model": settings.qwen_model,
        "temperature": 0,
    }
    base_kwargs.update(overrides)

    llm = ChatOpenAI(**base_kwargs)

    # 把当前 trace 上下文快照作为 metadata 绑定到 Runnable，
    # run_name 统一为 ``chatbi.llm`` 便于 LangSmith 聚合。
    return llm.with_config(
        RunnableConfig(metadata=trace_metadata(), run_name="chatbi.llm")
    )
