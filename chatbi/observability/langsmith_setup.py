"""LangSmith 追踪接入初始化模块。

本模块负责把 :mod:`chatbi.infra.config.settings` 中的 LangSmith 配置
注入为 LangChain SDK 识别的环境变量（``LANGCHAIN_*``），并在启动阶段
对 LangSmith API 端点做一次轻量探活。

设计要点：

* 缺少 ``LANGSMITH_API_KEY`` 时不抛异常，仅 warn，业务可继续运行；
* 探活失败也只 warn，避免外网不可达时阻塞本地开发；
* 项目名遵循 ``chatbi-{env}`` 约定：当配置中的 ``langsmith_project``
  保持默认 ``chatbi-dev`` 或为空时，自动按 ``chatbi_env`` 拼装。
"""

from __future__ import annotations

import os

from chatbi.infra.config.settings import get_settings
from chatbi.infra.logging import get_logger

# LangSmith / LangChain Tracer 端点（v2 协议）。
_LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"

# 默认项目名占位：与 settings.Settings.langsmith_project 默认值保持一致。
_DEFAULT_PROJECT_PLACEHOLDER = "chatbi-dev"

_logger = get_logger(__name__)


def _resolve_project(raw_project: str, env: str) -> str:
    """根据配置和环境名解析最终的 LangSmith 项目名。

    规则：

    * 若 ``raw_project`` 为空字符串或仍是默认占位值 ``chatbi-dev``，
      则以 ``chatbi-{env}`` 重新拼装；
    * 否则原样返回，尊重用户显式覆盖。

    Args:
        raw_project: ``settings.langchain_project`` 的原始值。
        env: ``settings.chatbi_env``（dev / staging / prod 等）。

    Returns:
        str: 最终用于 ``LANGCHAIN_PROJECT`` 的项目名。
    """

    if not raw_project or raw_project == _DEFAULT_PROJECT_PLACEHOLDER:
        return f"chatbi-{env or 'dev'}"
    return raw_project


def init() -> bool:
    """初始化 LangSmith 接入。

    流程：

    1. 读取 :func:`get_settings` 中的 LangSmith 相关字段；
    2. 若 ``langsmith_api_key`` 为空，warn 后返回 ``False``；
    3. 写入 LangChain SDK 识别的四个环境变量；
    4. 通过 ``httpx.get`` 以 5 秒超时探测 ``/info`` 端点，仅 warn 不抛；
    5. 成功后 info 日志并返回 ``True``。

    Returns:
        bool: 是否启用了 LangSmith 上报。
    """

    settings = get_settings()
    project = _resolve_project(settings.langchain_project, settings.chatbi_env)

    if not settings.langsmith_api_key:
        # 没有 key 视为本地 / 离线模式，明确告知但不影响主流程。
        _logger.warning(
            "未检测到 LANGSMITH_API_KEY，本次运行不上报追踪",
            extra={"event": "langsmith_missing_key"},
        )
        return False

    # 写入 LangChain Tracer 约定的环境变量，使后续任何
    # LangChain Runnable 调用都自动上报到指定项目。
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_ENDPOINT"] = _LANGSMITH_ENDPOINT
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = project

    # 轻量探活：只是为了在启动阶段尽早暴露网络 / Key 问题，
    # 任何异常都不应阻塞业务，因此统一吞掉只打 warning。
    try:
        import httpx  # 延迟 import，便于无网环境跑单测时不强依赖。

        httpx.get(f"{_LANGSMITH_ENDPOINT}/info", timeout=5.0)
    except Exception as exc:  # noqa: BLE001 - 故意宽捕获
        _logger.warning(
            "LangSmith 端点探活失败，将继续启动",
            extra={"event": "langsmith_probe_failed", "error": str(exc)},
        )

    _logger.info(f"LangSmith 接入成功，项目：{project}")
    return True
