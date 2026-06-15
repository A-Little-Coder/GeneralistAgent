"""ChatBI 配置加载模块。

`.env` 已在 `chatbi/__init__.py` 顶部由 `python-dotenv` 加载到 `os.environ`，
本模块只是把环境变量按业务字段分组、提供默认值，并做一次 lru_cache 单例。

优先级：环境变量 > `.env` > 这里写死的默认值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """ChatBI 全局运行时配置。"""

    # LangSmith
    langsmith_api_key: str
    langchain_project: str

    # 运行环境
    chatbi_env: str

    # Qwen / DashScope（OpenAI 兼容协议）
    qwen_api_key: str
    qwen_base_url: str
    qwen_model: str

    # 日志
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取一次环境变量并返回 Settings 单例。

    单测改完环境变量后请显式 ``get_settings.cache_clear()``。
    """
    return Settings(
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY", ""),
        langchain_project=os.getenv("LANGCHAIN_PROJECT", "chatbi-dev"),
        chatbi_env=os.getenv("CHATBI_ENV", "dev"),
        qwen_api_key=os.getenv("QWEN_API_KEY", ""),
        qwen_base_url=os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        qwen_model=os.getenv("QWEN_MODEL", "qwen-plus"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
