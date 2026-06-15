"""ChatBI 日志规范封装。

提供两个对外函数：

    - `configure_logging(level)`：在进程入口处调用一次（多次调用幂等），
      使用 `rich.logging.RichHandler` 作为 root handler，并降低部分
      第三方噪音 logger 的级别（例如 `uvicorn.access`）。
    - `get_logger(name)`：返回 `_StructuredAdapter` 包装后的 LoggerAdapter。
      调用方使用 `logger.info("xxx", extra={"event": "xxx", "user_id": "u1"})`
      的方式注入结构化字段；若调用方未提供 `event`，会自动补 `"log"`。

日志格式：`%(asctime)s | %(levelname)s | %(name)s | %(message)s`，
时间格式：`%Y-%m-%d %H:%M:%S`。
"""

from __future__ import annotations

import logging
from typing import Any, MutableMapping

from rich.logging import RichHandler

# 统一的日志格式与时间格式，供 RichHandler 复用
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    """配置 root logger，多次调用幂等。

    每次调用都会先清空 root logger 的 handlers，避免重复添加导致
    日志重复打印；随后挂载一个统一的 `RichHandler`。

    Args:
        level: 日志级别字符串（DEBUG / INFO / WARNING / ERROR / CRITICAL）。
            非法字符串会让 `setLevel` 抛错，调用方应自行确保正确。
    """

    root_logger = logging.getLogger()
    # 先清掉旧 handler，保证幂等
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # RichHandler：show_time=False 让时间字段交给 format 控制，避免重复
    rich_handler = RichHandler(rich_tracebacks=True, show_time=False)
    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
    rich_handler.setFormatter(formatter)

    root_logger.addHandler(rich_handler)
    root_logger.setLevel(level)

    # 第三方噪音 logger 降级，减少访问日志刷屏
    logging.getLogger("uvicorn.access").setLevel("WARNING")


class _StructuredAdapter(logging.LoggerAdapter):
    """结构化日志适配器。

    保证调用方传入的 `extra` 字典存在；当 `event` 字段缺失时填默认值
    `"log"`，统一约束日志事件名。
    """

    def process(
        self,
        msg: Any,
        kwargs: MutableMapping[str, Any],
    ) -> tuple[Any, MutableMapping[str, Any]]:
        # 取出（或创建）extra 字典，确保后续 setdefault 不会作用到 None
        extra = kwargs.get("extra")
        if not isinstance(extra, dict):
            extra = {}
        extra.setdefault("event", "log")
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> logging.LoggerAdapter:
    """获取带结构化字段默认值的 LoggerAdapter。

    Args:
        name: logger 名称，建议使用模块的 `__name__`。

    Returns:
        logging.LoggerAdapter: `_StructuredAdapter` 实例，可直接调用
        `.info / .warning / .error` 等方法，并通过 `extra=` 注入结构化字段。
    """

    base_logger = logging.getLogger(name)
    return _StructuredAdapter(base_logger, {})
