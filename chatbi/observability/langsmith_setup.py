"""LangSmith 启动状态检查。

LangChain SDK 会自动从环境变量读取 ``LANGCHAIN_TRACING_V2`` /
``LANGSMITH_API_KEY`` / ``LANGCHAIN_PROJECT``；dotenv 已经把 ``.env``
加载进 ``os.environ``，本模块只做一件事：在启动时打一条日志，告诉
用户当前是否启用了 LangSmith 上报。
"""

from __future__ import annotations

import os

from chatbi.infra.logging import get_logger

_logger = get_logger(__name__)


def init() -> bool:
    """检查 LangSmith 上报是否就绪并打日志。

    Returns:
        bool: 是否启用了 LangSmith 上报。
    """
    enabled = (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
        and bool(os.getenv("LANGSMITH_API_KEY"))
    )
    if enabled:
        project = os.getenv("LANGCHAIN_PROJECT", "chatbi-dev")
        _logger.info(
            f"LangSmith 接入就绪，项目：{project}",
            extra={"event": "langsmith_ready"},
        )
    else:
        _logger.warning(
            "未启用 LangSmith 追踪（需 LANGCHAIN_TRACING_V2=true 且配置 LANGSMITH_API_KEY）",
            extra={"event": "langsmith_disabled"},
        )
    return enabled
