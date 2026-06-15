"""ChatBI CLI 入口。

子命令：
- `chatbi version`：打印项目版本号
- `chatbi hello-trace`：发起一次最小问答，验证 LangSmith 接入
"""

from __future__ import annotations

import typer

from chatbi import __version__
from chatbi.infra.config import get_settings
from chatbi.infra.logging import configure_logging, get_logger
from chatbi.observability import get_chat_model
from chatbi.observability.context import set_trace_context
from chatbi.observability.langsmith_setup import init as langsmith_init

app = typer.Typer(name="chatbi", help="ChatBI Agent 命令行入口", no_args_is_help=True)

_logger = get_logger(__name__)


@app.command(name="version")
def version_cmd() -> None:
    """打印 ChatBI 版本号。"""
    typer.echo(__version__)


@app.command(name="hello-trace")
def hello_trace_cmd(
    prompt: str = typer.Option(
        "请用中文回复：你好",
        "--prompt",
        "-p",
        help="发送给 LLM 的提示词",
    ),
) -> None:
    """跑一次最小问答，验证 LLM 调用与 LangSmith 接入。

    需要先在 .env 中配好 ``QWEN_API_KEY``；如果同时配了
    ``LANGSMITH_API_KEY``，结果会自动上报到 LangSmith。
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    langsmith_init()

    if not settings.qwen_api_key:
        _logger.error(
            "未检测到 QWEN_API_KEY，无法发起 LLM 调用",
            extra={"event": "hello_trace_missing_key"},
        )
        raise typer.Exit(code=1)

    # 给本次调用打上一个固定的 plan_run_id，方便在 LangSmith 后台搜
    with set_trace_context(plan_run_id="hello-trace"):
        llm = get_chat_model("default")
        response = llm.invoke(prompt)

    answer = getattr(response, "content", str(response))
    typer.echo(answer)
    _logger.info(
        "hello-trace 完成",
        extra={"event": "hello_trace_done", "model": settings.qwen_model},
    )


if __name__ == "__main__":  # pragma: no cover
    app()
