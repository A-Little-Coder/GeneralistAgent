"""
编排工具与端到端"问数"链路的集成测试。

不依赖真实 LLM —— 直接调用工具，验证 Leader 通过这些工具能否完成：
  team_create → spawn_teammate(proxy_service=...) → assign_task →
  Teammate Runner 自动领任务 → 调 HTTP mock → 完成 → task_list_query 可见
"""

from __future__ import annotations

import asyncio
import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.core.config import Config
from src.orchestration.proxy_tools import ProxyServiceConfig
from src.orchestration.team import TeamManager
from src.orchestration.teammate import Teammate
from src.orchestration.tools import (
    OrchestrationContext,
    build_orchestration_tools,
)


# ── mock 问数 HTTP server ─────────────────────────────────────────────


class _MockChatBI(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        question = body.get("question", "")
        resp = {
            "status": "ok",
            "sql": f"SELECT * FROM t WHERE q='{question}'",
            "rows": [{"v": 1}],
        }
        payload = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args, **_kwargs):
        pass


@pytest.fixture
def mock_server():
    srv = HTTPServer(("127.0.0.1", 0), _MockChatBI)
    port = srv.server_address[1]
    t = Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


# ── 测试用 fixtures ───────────────────────────────────────────────────


@pytest.fixture
def fake_model():
    """Leader / Teammate 的占位模型 —— 不真的对话。"""
    return GenericFakeChatModel(messages=iter([]))


@pytest.fixture
def orchestration_ctx(tmp_path, mock_server, fake_model):
    """构造一套完整的编排上下文：TeamManager + Config（含 chatbi 代理服务）。"""
    # skills_dir 准备
    skills_dir = tmp_path / "skills"
    (skills_dir / "proxy_chatbi").mkdir(parents=True, exist_ok=True)
    (skills_dir / "proxy_chatbi" / "SKILL.md").write_text(
        "---\nname: proxy_chatbi\n---\n占位", encoding="utf-8"
    )

    # Config
    chatbi_svc = ProxyServiceConfig(
        name="chatbi",
        access_kind="http",
        base_url=mock_server,
        timeout=5,
    )
    config = Config(
        api_key="x", base_url="x", model_name="x",
        skills_dir=str(skills_dir),
        remote_db_dir=str(tmp_path / "remote"),
        teams_root=str(tmp_path / "teams"),
        proxy_services=[chatbi_svc],
    )

    tm = TeamManager(teams_root=tmp_path / "teams")
    ctx = OrchestrationContext(
        team_manager=tm,
        config=config,
        leader_model=fake_model,
    )
    yield ctx
    # 清理
    asyncio.get_event_loop().run_until_complete(tm.cleanup_all()) \
        if False else None  # 由各测试自己关团队


# ── tool helpers ──────────────────────────────────────────────────────


def _t(tools: list, name: str):
    """从工具列表里按名找 tool。"""
    return next(t for t in tools if t.name == name)


# ── 1. team_create / team_list / team_delete ─────────────────────────


async def test_team_create_and_list(orchestration_ctx):
    tools = build_orchestration_tools(orchestration_ctx)

    r = _t(tools, "team_create").invoke({"team_name": "alpha"})
    assert r["status"] == "ok"
    assert r["team"] == "alpha"

    r = _t(tools, "team_list").invoke({})
    assert any(t["name"] == "alpha" for t in r["teams"])

    # 重复创建
    r = _t(tools, "team_create").invoke({"team_name": "alpha"})
    assert r["status"] == "error"
    assert "已存在" in r["reason"]

    # 删除
    r = await _t(tools, "team_delete").ainvoke({"team_name": "alpha"})
    assert r["status"] == "ok"


# ── 2. spawn_teammate 未知服务 ────────────────────────────────────────


async def test_spawn_teammate_unknown_proxy(orchestration_ctx):
    tools = build_orchestration_tools(orchestration_ctx)
    _t(tools, "team_create").invoke({"team_name": "main"})

    r = await _t(tools, "spawn_teammate").ainvoke({
        "name": "proxy_foo",
        "proxy_service": "no-such-service",
        "team_name": "main",
    })
    assert r["status"] == "error"
    assert "no-such-service" in r["reason"]

    await _t(tools, "team_delete").ainvoke({"team_name": "main", "force": True})


# ── 3. 端到端：spawn → assign_task → 等到完成 → task_list_query ───────


async def test_e2e_orchestration_chatbi(orchestration_ctx, monkeypatch):
    """完整链路：编排工具 + 代理 Teammate + HTTP mock。"""
    tools = build_orchestration_tools(orchestration_ctx)

    # 1) 建团
    r = _t(tools, "team_create").invoke({"team_name": "main"})
    assert r["status"] == "ok"

    # 2) 拉起代理 Teammate（同时验证工具列表里有 chatbi_query）
    r = await _t(tools, "spawn_teammate").ainvoke({
        "name": "chatbi_proxy",
        "proxy_service": "chatbi",
        "team_name": "main",
    })
    assert r["status"] == "ok"
    assert "chatbi_query" in r["tools"]

    # 3) 把 Teammate 的 _agent 替换成 fake，直接调工具
    # 注：自 add-memory-persistence 起，Runner 在启动时一次性构建并缓存 agent，
    # 所以测试需替换 runner._agent，而非 teammate.build_agent_for_prompt
    team = orchestration_ctx.team_manager.get("main")
    teammate, runner = team.members["chatbi_proxy"]

    class _FakeAgent:
        def __init__(self, tools_):
            self._chatbi = next(t for t in tools_ if t.name == "chatbi_query")

        async def astream(self, state, config=None, stream_mode=None):
            user = state["messages"][-1].content
            out = await self._chatbi.ainvoke({"question": user})
            yield ("updates", {"agent": {"messages": [
                AIMessage(content=f"完成；SQL={out['sql']}")
            ]}})

    # 让 Runner 用 fake；保持 build_agent_for_prompt 兼容，仍替换签名
    fake_agent = _FakeAgent(teammate.tools)
    teammate.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: fake_agent  # type: ignore
    runner._agent = fake_agent

    # 4) assign_task
    r = _t(tools, "assign_task").invoke({
        "teammate_name": "chatbi_proxy",
        "description": "近 7 天华东大区销售总额",
        "team_name": "main",
    })
    assert r["status"] == "ok"
    task_id = r["task_id"]

    # 5) 等待 Runner 完成
    for _ in range(60):
        await asyncio.sleep(0.05)
        q = _t(tools, "task_list_query").invoke({"team_name": "main"})
        done = [t for t in q["tasks"] if t["id"] == task_id and t["status"] == "completed"]
        if done:
            assert "SELECT * FROM t" in done[0]["result"]
            break
    else:
        pytest.fail("任务未在超时内完成")

    # 6) 清理
    r = await _t(tools, "team_delete").ainvoke({"team_name": "main", "force": True})
    assert r["status"] == "ok"


# ── 4. send_message 唤醒 Teammate ────────────────────────────────────


async def test_send_message_to_teammate(orchestration_ctx):
    tools = build_orchestration_tools(orchestration_ctx)
    _t(tools, "team_create").invoke({"team_name": "main"})
    r = await _t(tools, "spawn_teammate").ainvoke({
        "name": "chatbi_proxy",
        "proxy_service": "chatbi",
        "team_name": "main",
    })
    assert r["status"] == "ok"

    # 替 fake，避免真打 LLM（Runner 启动后已缓存 agent，故同时替换 _agent）
    team = orchestration_ctx.team_manager.get("main")
    teammate, runner = team.members["chatbi_proxy"]
    received: list[str] = []

    class _Fake:
        async def astream(self, state, config=None, stream_mode=None):
            received.append(state["messages"][-1].content)
            yield ("updates", {"agent": {"messages": [AIMessage(content="ack")]}})

    fake = _Fake()
    teammate.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: fake  # type: ignore
    runner._agent = fake

    r = await _t(tools, "send_message").ainvoke({
        "to": "chatbi_proxy",
        "content": "ping",
        "team_name": "main",
    })
    assert r["status"] == "ok"
    assert r["delivered_count"] == 1

    # 等 Runner 处理
    for _ in range(40):
        await asyncio.sleep(0.05)
        if received:
            break
    assert received == ["ping"]

    await _t(tools, "team_delete").ainvoke({"team_name": "main", "force": True})


# ── 5. 退出清理钩子（4.4） ────────────────────────────────────────────


async def test_cleanup_all_shuts_down_runners(orchestration_ctx):
    tools = build_orchestration_tools(orchestration_ctx)
    _t(tools, "team_create").invoke({"team_name": "main"})
    await _t(tools, "spawn_teammate").ainvoke({
        "name": "chatbi_proxy",
        "proxy_service": "chatbi",
        "team_name": "main",
    })

    team = orchestration_ctx.team_manager.get("main")
    assert team.has_active_members()

    await orchestration_ctx.team_manager.cleanup_all()

    # 清理后团队应不存在
    assert orchestration_ctx.team_manager.get("main") is None
