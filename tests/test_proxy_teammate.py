"""
代理 Teammate 工具与配置解析单元测试。

覆盖：
  - ProxyServiceConfig 默认值与 resolved_skill_name
  - HTTP 工具：成功 / 4xx 不重试 / 5xx 重试一次 / 网络错误重试一次
  - MCP 工具：占位（抛 NotImplementedError）
  - Config._parse_proxy_services_from_env：多服务聚合、缺 ACCESS_KIND 跳过
  - create_proxy_teammate：装配工具 + skills_dir 限定
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from src.core.config import _parse_proxy_services_from_env
from src.orchestration.proxy_tools import (
    ProxyServiceConfig,
    build_proxy_tools,
)
from src.orchestration.teammate import create_proxy_teammate


# ── 1. ProxyServiceConfig ─────────────────────────────────────────────


def test_resolved_skill_name_default():
    svc = ProxyServiceConfig(name="chatbi", access_kind="http", base_url="http://x")
    assert svc.resolved_skill_name() == "proxy-chatbi"


def test_resolved_skill_name_custom():
    svc = ProxyServiceConfig(name="chatbi", access_kind="http", skill_name="my_skill")
    assert svc.resolved_skill_name() == "my_skill"


# ── 2. HTTP 工具行为（用 httpx MockTransport 拦截） ────────────────────


def _make_http_tool(handler):
    """用自定义 handler 注入到 httpx.AsyncClient，构造一个 HTTP 代理工具。

    handler: (request) -> httpx.Response
    """
    svc = ProxyServiceConfig(name="chatbi", access_kind="http",
                             base_url="http://fake", timeout=2)
    tool = build_proxy_tools(svc)[0]

    # monkeypatch httpx.AsyncClient 的 transport：用 MockTransport
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init
    return tool, lambda: setattr(httpx.AsyncClient, "__init__", original_init)


async def test_http_tool_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/query"
        return httpx.Response(200, json={"status": "ok", "sql": "SELECT 1", "rows": []})

    tool, restore = _make_http_tool(handler)
    try:
        out = await tool.ainvoke({"question": "近 7 天销售"})
        assert out == {"status": "ok", "sql": "SELECT 1", "rows": []}
    finally:
        restore()


async def test_http_tool_4xx_no_retry():
    """4xx 不重试，直接返回 error 结构。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, text="bad request")

    tool, restore = _make_http_tool(handler)
    try:
        out = await tool.ainvoke({"question": "x"})
        assert call_count == 1
        assert out["status"] == "error"
        assert out["http_status"] == 400
    finally:
        restore()


async def test_http_tool_5xx_retry_once():
    """5xx 重试 1 次，第 2 次成功则返回。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(500, text="server error")
        return httpx.Response(200, json={"status": "ok"})

    tool, restore = _make_http_tool(handler)
    try:
        out = await tool.ainvoke({"question": "x"})
        assert call_count == 2
        assert out == {"status": "ok"}
    finally:
        restore()


async def test_http_tool_timeout_retry_once():
    """超时也只重试一次，最终失败返回 error 结构。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("simulated timeout")

    tool, restore = _make_http_tool(handler)
    try:
        out = await tool.ainvoke({"question": "x"})
        assert call_count == 2
        assert out["status"] == "error"
        assert "ConnectTimeout" in out["reason"]
    finally:
        restore()


# ── 3. MCP 工具（占位） ───────────────────────────────────────────────


async def test_mcp_tool_not_implemented():
    svc = ProxyServiceConfig(name="foo", access_kind="mcp", mcp_command="echo")
    tool = build_proxy_tools(svc)[0]
    with pytest.raises(NotImplementedError):
        await tool.ainvoke({"question": "x"})


# ── 4. Config 解析 ────────────────────────────────────────────────────


def test_parse_proxy_services_basic(monkeypatch):
    """两个服务，HTTP + MCP，能正确聚合。"""
    # 先清干净环境
    for k in list(os.environ.keys()):
        if k.startswith("PROXY_"):
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("PROXY_CHATBI_ACCESS_KIND", "http")
    monkeypatch.setenv("PROXY_CHATBI_BASE_URL", "http://host:8000")
    monkeypatch.setenv("PROXY_CHATBI_AUTH_HEADER", "Bearer abc")
    monkeypatch.setenv("PROXY_CHATBI_TIMEOUT", "15")

    monkeypatch.setenv("PROXY_FOO_ACCESS_KIND", "mcp")
    monkeypatch.setenv("PROXY_FOO_MCP_COMMAND", "python -m foo")

    services = _parse_proxy_services_from_env()
    by_name = {s.name: s for s in services}
    assert set(by_name) == {"chatbi", "foo"}

    chatbi = by_name["chatbi"]
    assert chatbi.access_kind == "http"
    assert chatbi.base_url == "http://host:8000"
    assert chatbi.auth_header == "Bearer abc"
    assert chatbi.timeout == 15

    foo = by_name["foo"]
    assert foo.access_kind == "mcp"
    assert foo.mcp_command == "python -m foo"


def test_parse_proxy_services_skip_missing_access_kind(monkeypatch):
    """没有声明 ACCESS_KIND 的不会被注册。"""
    for k in list(os.environ.keys()):
        if k.startswith("PROXY_"):
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("PROXY_INCOMPLETE_BASE_URL", "http://x")  # 没 ACCESS_KIND
    services = _parse_proxy_services_from_env()
    assert all(s.name != "incomplete" for s in services)


def test_parse_proxy_services_invalid_timeout(monkeypatch):
    """TIMEOUT 不是合法整数则降级为默认 30。"""
    for k in list(os.environ.keys()):
        if k.startswith("PROXY_"):
            monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("PROXY_BAR_ACCESS_KIND", "http")
    monkeypatch.setenv("PROXY_BAR_BASE_URL", "http://x")
    monkeypatch.setenv("PROXY_BAR_TIMEOUT", "not-a-number")

    services = _parse_proxy_services_from_env()
    bar = next(s for s in services if s.name == "bar")
    assert bar.timeout == 30


# ── 5. create_proxy_teammate 装配 ─────────────────────────────────────


def test_create_proxy_teammate_assembles_tools_and_skills_dir(tmp_path: Path):
    """工厂方法应：装配工具 + skills_dir 限定到该 SKILL 子目录 + 注入角色 prompt。"""
    svc = ProxyServiceConfig(name="chatbi", access_kind="http", base_url="http://x")
    fallback = GenericFakeChatModel(messages=iter([]))

    teammate = create_proxy_teammate(
        name="proxy_chatbi_runner",
        team_name="test-team",
        service=svc,
        skills_root=str(tmp_path),
        fallback_model=fallback,
    )

    # 1) 装配了 HTTP 工具
    assert any(t.name == "chatbi_query" for t in teammate.tools)

    # 2) skills_dir 指向 skills/proxy-chatbi
    assert Path(teammate.skills_dir).name == "proxy-chatbi"

    # 3) extra_system_prompt 包含工具列表与 SKILL 名（牵引模型）
    assert "proxy-chatbi" in teammate.extra_system_prompt
    assert "chatbi_query" in teammate.extra_system_prompt
