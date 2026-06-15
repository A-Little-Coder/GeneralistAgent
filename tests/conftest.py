"""pytest 全局配置与共享 fixture。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """让每个测试看到一个干净、可控的环境，避免外部 .env 污染。

    1. 清掉所有 LANGSMITH_/QWEN_/CHATBI_/LANGCHAIN_ 前缀的环境变量；
       测试想要某个值再用 ``monkeypatch.setenv`` 注入。
    2. 把 cwd 切换到 tmp_path，这样 ``Settings(env_file=".env")``
       不会读到仓库根目录真实的 ``.env``。
    3. 强制关闭 LangChain 远端追踪，避免单测打 LangSmith 网络。
    """
    for key in list(os.environ.keys()):
        if key.startswith(("LANGSMITH_", "QWEN_", "CHATBI_", "LANGCHAIN_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """提供一个临时 .env 文件路径，测试可写入后让 Settings 加载。"""
    return tmp_path / ".env"
