"""``add-chatbi-foundation`` 验收测试。

覆盖：
- 子包可导入
- Settings 加载（环境变量优先级）
- ``get_chat_model`` 工厂返回 Runnable
- CLI ``version`` 子命令
- ``GET /healthz`` 路由
- 仓库内禁止直接 ``import openai``
- 默认 trace 上下文为空字符串
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.runnables import Runnable
from typer.testing import CliRunner


# ---------------------------------------------------------------------------
# 7.1 子包可导入
# ---------------------------------------------------------------------------

_SUBPACKAGES = [
    "chatbi",
    "chatbi.infra",
    "chatbi.infra.config",
    "chatbi.infra.logging",
    "chatbi.observability",
    "chatbi.cli",
    "chatbi.server",
]


@pytest.mark.parametrize("module_path", _SUBPACKAGES)
def test_packages_importable(module_path: str) -> None:
    """所有声明的子包都能被 import。"""
    module = importlib.import_module(module_path)
    assert module is not None


# ---------------------------------------------------------------------------
# 7.2 Settings 加载与优先级
# ---------------------------------------------------------------------------


def test_settings_loading_env_overrides_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量优先级最高。"""
    from chatbi.infra.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("LANGCHAIN_PROJECT", "chatbi-staging")
    monkeypatch.setenv("CHATBI_ENV", "staging")

    settings = get_settings()
    try:
        assert settings.langchain_project == "chatbi-staging"
        assert settings.chatbi_env == "staging"
    finally:
        get_settings.cache_clear()


def test_settings_loading_defaults() -> None:
    """无任何环境变量时使用默认值。"""
    from chatbi.infra.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    try:
        assert settings.langchain_project == "chatbi-dev"
        assert settings.chatbi_env == "dev"
        assert settings.qwen_model
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 7.3 get_chat_model 返回 Runnable
# ---------------------------------------------------------------------------


def test_get_chat_model_returns_runnable(monkeypatch: pytest.MonkeyPatch) -> None:
    """mock QWEN_API_KEY 后工厂应返回 Runnable / BaseChatModel。"""
    from chatbi.infra.config import get_settings
    from chatbi.observability import get_chat_model

    get_settings.cache_clear()
    monkeypatch.setenv("QWEN_API_KEY", "test-key-xxx")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    try:
        llm = get_chat_model("default")
        assert llm is not None
        # with_config 之后是 RunnableBinding，仍是 Runnable 子类
        assert isinstance(llm, Runnable)
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 7.4 CLI version
# ---------------------------------------------------------------------------


def test_cli_version() -> None:
    """``chatbi version`` 输出非空版本号。"""
    from chatbi import __version__
    from chatbi.cli.main import app

    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


# ---------------------------------------------------------------------------
# 7.5 /healthz 路由
# ---------------------------------------------------------------------------


def test_healthz() -> None:
    """``GET /healthz`` 返回 200 + ``{"status":"ok"}``。"""
    from chatbi.server.app import app

    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 7.6 禁止 import openai 原生 SDK
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHATBI_DIR = _REPO_ROOT / "chatbi"


def _walk_python_files(root: Path):
    for path in root.rglob("*.py"):
        yield path


def _imports_native_openai(tree: ast.AST) -> bool:
    """检查 AST 中是否存在 ``import openai`` 或 ``from openai...``。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openai" or alias.name.startswith("openai."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "openai" or module.startswith("openai."):
                return True
    return False


def test_no_native_llm_sdk() -> None:
    """仓库代码不得直接 import 原生 openai SDK；必须经 langchain_openai。"""
    offenders: list[str] = []
    for path in _walk_python_files(_CHATBI_DIR):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:  # pragma: no cover - 跳过解析失败的文件
            continue
        if _imports_native_openai(tree):
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert not offenders, (
        f"以下文件直接 import openai，违反 LLM 调用必须经 langchain 的约定：{offenders}"
    )


# ---------------------------------------------------------------------------
# 7.7 默认 trace 上下文为空字符串
# ---------------------------------------------------------------------------


def test_trace_context_defaults() -> None:
    """未进入 set_trace_context 时，所有字段为空字符串/0。"""
    from chatbi.observability.context import get_trace_context, trace_metadata

    ctx = get_trace_context()
    assert ctx.user_id == ""
    assert ctx.conv_id == ""
    assert ctx.plan_run_id == ""
    assert ctx.retry_attempt == 0

    meta = trace_metadata()
    assert meta["user_id"] == ""
    assert meta["conv_id"] == ""
    assert meta["plan_run_id"] == ""
    # retry_attempt 已被 str 化
    assert meta["retry_attempt"] == "0"
