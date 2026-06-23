"""
NL2SQL 专属适配工具测试。

覆盖：
  - nl2sql_query：SSE 流成功 / 错误 / done 无结果 / 网络超时
  - nl2sql_list_databases：成功 / 错误
  - nl2sql_list_tables：成功 / 错误
  - build_proxy_tools 调度 nl2sql_sse 分支
"""

from __future__ import annotations

import httpx
import pytest

from src.orchestration.nl2sql_tools import build_nl2sql_tools
from src.orchestration.proxy_tools import ProxyServiceConfig, build_proxy_tools


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def svc():
    return ProxyServiceConfig(
        name="chatbi",
        access_kind="nl2sql_sse",
        base_url="http://fake",
        timeout=10,
    )


def _intercept(handler):
    """用 MockTransport 替换 httpx.AsyncClient transport。"""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init
    return lambda: setattr(httpx.AsyncClient, "__init__", original_init)


# ── 1. nl2sql_query — SSE 流成功 ─────────────────────────────────────


def _make_sse_events(*events: str) -> str:
    """SSE 格式的 data 行拼接（服务端按 \\n\\n 分隔）。"""
    return "".join(f"data: {e}\n\n" for e in events)


async def test_query_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query"
        assert "db_id" in request.content.decode()

        sse = _make_sse_events(
            '{"type":"stage","data":{"node":"schema_recall"}}',
            '{"type":"result","data":{"sql":"SELECT 1","result":[{"v":1}],"query_id":"q1"}}',
            '{"type":"done","data":{"has_result":true}}',
        )
        return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_query")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({"question": "近 7 天销售", "db_id": "sales"})
        assert out["status"] == "ok"
        assert "SELECT 1" in out["sql"]
        assert out["result"] == [{"v": 1}]
        assert "q1" in out["query_id"]
    finally:
        restore()


async def test_query_error_event():
    def handler(request: httpx.Request) -> httpx.Response:
        sse = _make_sse_events(
            '{"type":"error","data":{"error":"数据库 sales 不存在，请先检查可用数据库列表。","rejection":true}}',
            '{"type":"done","data":{"has_result":false}}',
        )
        return httpx.Response(200, text=sse)

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_query")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({"question": "x", "db_id": "sales"})
        assert out["status"] == "error"
        assert "数据库 sales" in out["reason"]
        assert out["rejection"] is True
    finally:
        restore()


async def test_query_http_400():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, text='{"detail": "session_id 字段必填"}')

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_query")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({"question": "x", "db_id": "s"})
        assert out["status"] == "error"
        assert out["http_status"] == 422
    finally:
        restore()


async def test_query_network_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_query")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({"question": "x", "db_id": "s"})
        assert out["status"] == "error"
        assert "ConnectTimeout" in out["reason"]
    finally:
        restore()


# ── 2. nl2sql_list_databases ─────────────────────────────────────────


async def test_list_databases_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/databases"
        return httpx.Response(200, json={
            "databases": [
                {"db_id": "sales", "db_path": "/d/sales.sqlite"},
                {"db_id": "hr", "db_path": "/d/hr.sqlite"},
            ]
        })

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_list_databases")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({})
        assert out["status"] == "ok"
        assert "sales" in out["databases"]
        assert "hr" in out["databases"]
    finally:
        restore()


# ── 3. nl2sql_list_tables ────────────────────────────────────────────


async def test_list_tables_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api/v1/databases/sales/tables" in str(request.url)
        return httpx.Response(200, json={
            "db_id": "sales",
            "tables": ["orders", "products", "customers"],
        })

    tools = build_nl2sql_tools(ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    ))
    tool = next(t for t in tools if t.name == "nl2sql_list_tables")
    restore = _intercept(handler)
    try:
        out = await tool.ainvoke({"db_id": "sales"})
        assert out["status"] == "ok"
        assert "orders" in out["tables"]
    finally:
        restore()


# ── 4. build_proxy_tools 调度 nl2sql_sse ──────────────────────────────


def test_build_proxy_tools_nl2sql_sse():
    """验证 build_proxy_tools 调度到 nl2sql 分支且返回三个工具。"""
    svc = ProxyServiceConfig(
        name="chatbi", access_kind="nl2sql_sse", base_url="http://fake", timeout=10,
    )
    tools = build_proxy_tools(svc)
    names = {t.name for t in tools}
    assert names == {"nl2sql_query", "nl2sql_list_databases", "nl2sql_list_tables"}