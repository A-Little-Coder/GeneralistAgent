"""
阶段 6 新增能力测试：
  - Runner 任务/消息完成后自动给 Leader 投递 Mailbox 通知（kind=task_completed / task_failed）
  - wait_for_message 工具阻塞等回信，支持 timeout
  - NL2SQL 连接失败时返回明确错误并打印日志
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.core.config import Config
from src.orchestration.mailbox import Mailbox, Message
from src.orchestration.proxy_tools import ProxyServiceConfig
from src.orchestration.runner import Runner
from src.orchestration.task_list import TaskList
from src.orchestration.team import TeamManager
from src.orchestration.teammate import Teammate
from src.orchestration.tools import OrchestrationContext, build_orchestration_tools


# ── fake agent for Runner ────────────────────────────────────────────


class _FakeAgent:
    """模拟 deepagents 的 astream：直接 yield 一条 AIMessage。"""
    def __init__(self, reply: str = "ok", raise_exc: Exception | None = None):
        self._reply = reply
        self._raise = raise_exc

    async def astream(self, state, config=None, stream_mode=None):
        if self._raise is not None:
            raise self._raise
        yield ("updates", {"agent": {"messages": [AIMessage(content=self._reply)]}})


def _patch(teammate: Teammate, agent: _FakeAgent):
    teammate.build_agent_for_prompt = lambda base_prompt="": agent  # type: ignore


# ── 1. Runner 自动投递 task_completed ─────────────────────────────────


async def test_runner_sends_task_completed_to_leader(tmp_path: Path):
    """任务完成后 Runner 应自动给 Leader 投 kind=task_completed 的 Mailbox 消息。"""
    tm = Teammate(name="data-agent", team_name="t1", model=None, tools=[])
    _patch(tm, _FakeAgent(reply="查到 42 行"))
    mb = Mailbox()
    mb.register("leader")
    tl = TaskList(tmp_path, "t1")
    runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05, leader_name="leader")
    runner.start()
    try:
        task = tl.create("查询 X")
        msg = await asyncio.wait_for(mb.recv("leader"), timeout=3.0)
        assert msg.sender == "data-agent"
        assert msg.kind == "task_completed"
        assert msg.content == "查到 42 行"
        assert msg.meta.get("task_id") == task.id
        assert msg.meta.get("teammate_name") == "data-agent"
        # TaskList 也应标记 completed
        assert tl.get(task.id).status == "completed"
    finally:
        await runner.request_shutdown()
        await runner.wait_done()


async def test_runner_sends_task_failed_on_exception(tmp_path: Path):
    """Runner 内部抛错时应投递 kind=task_failed，content 含异常摘要。"""
    tm = Teammate(name="brittle-agent", team_name="t1", model=None, tools=[])
    _patch(tm, _FakeAgent(raise_exc=RuntimeError("boom")))
    mb = Mailbox()
    mb.register("leader")
    tl = TaskList(tmp_path, "t1")
    runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05, leader_name="leader")
    runner.start()
    try:
        task = tl.create("挑事")
        msg = await asyncio.wait_for(mb.recv("leader"), timeout=3.0)
        assert msg.kind == "task_failed"
        assert "boom" in msg.content
        assert msg.meta.get("task_id") == task.id
        # 即使失败，TaskList 也得 complete（result 写了失败信息），免得任务卡 in_progress
        assert tl.get(task.id).status == "completed"
    finally:
        await runner.request_shutdown()
        await runner.wait_done()


async def test_runner_replies_to_message_sender(tmp_path: Path):
    """普通消息处理完毕后应回信原 sender（kind=message_reply），而非 leader。"""
    tm = Teammate(name="echo-agent", team_name="t1", model=None, tools=[])
    _patch(tm, _FakeAgent(reply="echo: hi"))
    mb = Mailbox()
    mb.register("alice")
    tl = TaskList(tmp_path, "t1")
    runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05, leader_name="leader")
    runner.start()
    try:
        await mb.send(Message(sender="alice", to="echo-agent", content="hi"))
        reply = await asyncio.wait_for(mb.recv("alice"), timeout=3.0)
        assert reply.sender == "echo-agent"
        assert reply.kind == "message_reply"
        assert "echo" in reply.content
        assert reply.meta.get("teammate_name") == "echo-agent"
    finally:
        await runner.request_shutdown()
        await runner.wait_done()


# ── 2. wait_for_message 工具 ─────────────────────────────────────────


def _make_ctx(tmp_path: Path) -> OrchestrationContext:
    """构造一个最小 OrchestrationContext（不会触发真实 LLM）。"""
    config = Config(
        api_key="x", base_url="x", model_name="x",
        skills_dir=str(tmp_path / "skills"),
        remote_db_dir=str(tmp_path / "remote"),
        teams_root=str(tmp_path / "teams"),
        proxy_services=[],
    )
    tm = TeamManager(teams_root=tmp_path / "teams")
    fake = GenericFakeChatModel(messages=iter([]))
    return OrchestrationContext(team_manager=tm, config=config, leader_model=fake)


async def test_wait_for_message_returns_on_delivery(tmp_path: Path):
    """有消息到达时 wait_for_message 立刻返回结构化 dict。"""
    ctx = _make_ctx(tmp_path)
    tools = build_orchestration_tools(ctx)
    next(t for t in tools if t.name == "team_create").invoke({"team_name": "main"})

    wait_tool = next(t for t in tools if t.name == "wait_for_message")
    team = ctx.team_manager.get("main")

    # 后台 0.1s 后投递
    async def deliver():
        await asyncio.sleep(0.1)
        await team.mailbox.send(Message(
            sender="data-agent", to="leader",
            content="done", kind="task_completed",
            meta={"task_id": "abc"},
        ))

    asyncio.create_task(deliver())
    out = await wait_tool.ainvoke({"timeout": 2.0, "team_name": "main"})
    assert out["status"] == "ok"
    assert out["from"] == "data-agent"
    assert out["kind"] == "task_completed"
    assert out["content"] == "done"
    assert out["meta"]["task_id"] == "abc"


async def test_wait_for_message_timeout(tmp_path: Path):
    """没人发消息时 timeout 内返回 status=timeout。"""
    ctx = _make_ctx(tmp_path)
    tools = build_orchestration_tools(ctx)
    next(t for t in tools if t.name == "team_create").invoke({"team_name": "main"})

    wait_tool = next(t for t in tools if t.name == "wait_for_message")
    out = await wait_tool.ainvoke({"timeout": 0.2, "team_name": "main"})
    assert out["status"] == "timeout"


# ── 3. NL2SQL 连接失败明确报错 ────────────────────────────────────────


async def test_nl2sql_connect_refused_logs_clear_error(capsys):
    """指向不存在的端口 → ConnectError，返回结构化 reason + 日志含错误前缀。"""
    from src.orchestration.nl2sql_tools import build_nl2sql_tools

    svc = ProxyServiceConfig(
        name="chatbi",
        access_kind="nl2sql_sse",
        # 注意：用 127.0.0.1 + 一个几乎肯定空着的高位端口
        base_url="http://127.0.0.1:1",
        timeout=2,
    )
    tools = build_nl2sql_tools(svc)
    query_tool = next(t for t in tools if t.name == "nl2sql_query")
    list_db_tool = next(t for t in tools if t.name == "nl2sql_list_databases")

    # 1) 查询请求
    out = await query_tool.ainvoke({"question": "x", "db_id": "x"})
    assert out["status"] == "error"
    # ConnectError / ConnectTimeout 都是合法可能
    assert "Connect" in out.get("reason", "") or "Timeout" in out.get("reason", "")

    # 2) databases 请求同样
    out2 = await list_db_tool.ainvoke({})
    assert out2["status"] == "error"
    assert "Connect" in out2.get("reason", "") or "Timeout" in out2.get("reason", "")

    # 3) 日志：含 [NL2SQL] 前缀 + ✗
    captured = capsys.readouterr()
    assert "[NL2SQL]" in captured.out
    assert "✗" in captured.out
