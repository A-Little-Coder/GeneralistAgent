"""
模型初始化模块 — 使用 LangChain init_chat_model 初始化 LLM。
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from src.core.config import Config


def init_model(config: Config) -> BaseChatModel:
    """根据配置初始化 LLM 模型。

    使用 LangChain 的 init_chat_model 统一接口，
    通过 provider:model 格式适配各种 LLM 服务商。
    """
    return init_chat_model(
        model=config.model_name,
        model_provider=config.model_provider,
        base_url=config.base_url,
        api_key=config.api_key,
    )