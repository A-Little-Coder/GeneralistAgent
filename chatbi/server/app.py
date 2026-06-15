"""ChatBI FastAPI 服务入口。

当前 change 仅提供：
- ``GET /healthz``：进程存活探针，返回 ``{"status": "ok"}``
- ``startup`` 事件：调用 ``configure_logging`` 与 ``langsmith_init``

更多业务路由（``/api/chat/*``、``/api/conversations`` 等）由
``add-streaming-conversation`` change 落地。
"""

from __future__ import annotations

from fastapi import FastAPI

from chatbi import __version__
from chatbi.infra.config import get_settings
from chatbi.infra.logging import configure_logging, get_logger
from chatbi.observability.langsmith_setup import init as langsmith_init

app = FastAPI(
    title="ChatBI Agent",
    version=__version__,
    description="供应链 BG ChatBI Web Chat 主入口的统一中控 Agent",
)

_logger = get_logger(__name__)


@app.on_event("startup")
async def _on_startup() -> None:
    """进程启动钩子：日志配置 → LangSmith 接入。"""
    settings = get_settings()
    configure_logging(settings.log_level)
    langsmith_init()
    _logger.info(
        "ChatBI 服务启动完成",
        extra={"event": "server_startup", "env": settings.chatbi_env},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """进程存活探针。

    与 ``GET /api/ready`` 区分：``/healthz`` 仅返回进程是否在跑，不检查 Redis、SQLite、LLM 等依赖。
    """
    return {"status": "ok"}
