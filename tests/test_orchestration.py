"""
多 Agent 协作基础设施单元测试。

覆盖（对应 specs/agent-team-orchestration）：
  - TeammateContext 同进程身份隔离（并发不混淆）
  - TaskList 创建、领取、状态流转、依赖
  - Mailbox 点对点、广播、注销
  - Runner idle 循环自动领任务 / 处理消息 / shutdown
  - Team 生命周期边界（重名、活跃成员、Teammate 不能 spawn / create_team）
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.orchestration.context import (
    TeammateContext,
    assign_color,
    format_agent_id,
    get_current_teammate,
    is_running_as_teammate,
    run_in_teammate_context,
)
from src.orchestration.mailbox import Mailbox, Message
from src.orchestration.task_list import TaskList
from src.orchestration.team import Team, TeamManager
from src.orchestration.teammate import Teammate
from src.orchestration.runner import Runner


# ── 公共 fixture ──────────────────────────────────────────────────────

@pytest.fixture
def teams_root(tmp_path: Path) -> Path:
    return tmp_path / "tasks"


# ── TeammateContext ────────────────────────────────────────────────────

class TestTeammateContext:
    """同进程并发身份隔离（contextvars 与 asyncio.Task 配合）。"""

    def test_no_context_outside_teammate(self):
        assert get_current_teammate() is None
        assert is_running_as_teammate() is False

    @pytest.mark.asyncio
    async def test_isolation_between_concurrent_teammates(self):
        """多个并发协程各自看到自己的 Teammate 身份。"""
        ctx_a = TeammateContext("a@t", "a", "t", "red")
        ctx_b = TeammateContext("b@t", "b", "t", "blue")
        seen: dict[str, list[str]] = {"a": [], "b": []}

        async def work(ctx: TeammateContext, label: str):
            async def body():
                for _ in range(3):
                    me = get_current_teammate()
                    seen[label].append(me.name)
                    await asyncio.sleep(0)
                return None
            await run_in_teammate_context(ctx, body)

        await asyncio.gather(work(ctx_a, "a"), work(ctx_b, "b"))
        assert seen["a"] == ["a", "a", "a"]
        assert seen["b"] == ["b", "b", "b"]
        # 退出后 Leader 上下文恢复为 None
        assert get_current_teammate() is None

    def test_format_and_color(self):
        tid = format_agent_id("researcher", "my-team")
        assert tid == "researcher@my-team"
        # color 稳定
        assert assign_color(tid) == assign_color(tid)


# ── TaskList ──────────────────────────────────────────────────────────

class TestTaskList:
    """共享 TaskList 行为。"""

    def test_create_and_get(self, teams_root: Path):
        tl = TaskList(teams_root, "t1")
        task = tl.create("查询数据")
        assert task.status == "pending"
        assert tl.get(task.id).description == "查询数据"

    def test_claim_lifecycle(self, teams_root: Path):
        tl = TaskList(teams_root, "t1")
        task = tl.create("do x")
        assert tl.claim(task.id, "alice@t1") is True
        assert tl.get(task.id).status == "in_progress"
        assert tl.get(task.id).owner == "alice@t1"
        # 再次 claim 失败
        assert tl.claim(task.id, "bob@t1") is False
        # complete
        assert tl.complete(task.id, result="结果")
        assert tl.get(task.id).status == "completed"

    def test_claimable_filters(self, teams_root: Path):
        tl = TaskList(teams_root, "t1")
        t_open = tl.create("anyone")
        t_assigned = tl.create("only alice", assignee="alice")
        # bob 看不到 alice 的任务
        names = [t.id for t in tl.claimable_for("bob")]
        assert t_open.id in names and t_assigned.id not in names
        # alice 两个都能领
        names = [t.id for t in tl.claimable_for("alice")]
        assert t_open.id in names and t_assigned.id in names

    def test_dependency_blocks_claim(self, teams_root: Path):
        tl = TaskList(teams_root, "t1")
        t1 = tl.create("先做")
        t2 = tl.create("后做", blocked_by=[t1.id])
        # 依赖未完成 → 不可领
        assert [t.id for t in tl.claimable_for("x")] == [t1.id]
        tl.claim(t1.id, "x@t1")
        tl.complete(t1.id)
        # 依赖完成后 → t2 可领
        assert t2.id in [t.id for t in tl.claimable_for("x")]


# ── Mailbox ──────────────────────────────────────────────────────────

class TestMailbox:
    """Mailbox 点对点、广播、注销。"""

    @pytest.mark.asyncio
    async def test_point_to_point(self):
        mb = Mailbox()
        mb.register("alice")
        await mb.send(Message(sender="leader", to="alice", content="hi"))
        msg = await mb.recv("alice")
        assert msg.content == "hi"

    @pytest.mark.asyncio
    async def test_broadcast_skips_sender(self):
        mb = Mailbox()
        mb.register("alice"); mb.register("bob"); mb.register("carol")
        sent = await mb.send(Message(sender="bob", to="*", content="all"))
        # 只发给 alice / carol，不发自己
        assert sent == 2
        assert mb.pending_count("bob") == 0
        assert mb.pending_count("alice") == 1

    @pytest.mark.asyncio
    async def test_send_to_unregistered_returns_zero(self):
        mb = Mailbox()
        sent = await mb.send(Message(sender="x", to="ghost", content="?"))
        assert sent == 0

    def test_try_recv_empty_returns_none(self):
        mb = Mailbox()
        mb.register("a")
        assert mb.try_recv("a") is None

    def test_unregister(self):
        mb = Mailbox()
        mb.register("a")
        mb.unregister("a")
        assert "a" not in mb.members()


# ── Runner ───────────────────────────────────────────────────────────

class _FakeAgent:
    """最小 fake agent：astream 返回一个 ai 消息更新。"""

    def __init__(self, reply: str):
        self._reply = reply

    async def astream(self, state, config, stream_mode):
        from langchain_core.messages import AIMessage
        yield ("updates", {"call": {"messages": [AIMessage(content=self._reply)]}})


def _patch_teammate(monkeypatch, teammate: Teammate, reply: str):
    """替换 Teammate.build_agent_for_prompt 返回 fake agent，避开 deepagents 真实工厂。"""
    def fake(self, base_prompt: str = ""):
        return _FakeAgent(reply)
    monkeypatch.setattr(teammate, "build_agent_for_prompt", fake.__get__(teammate, Teammate))


class TestRunner:
    """Runner idle 循环行为。"""

    def _make_teammate(self, name: str, team_name: str) -> Teammate:
        # 不用真实模型；下面会用 monkeypatch 替换 build_agent_for_prompt
        return Teammate(name=name, team_name=team_name, model=None, tools=[])

    @pytest.mark.asyncio
    async def test_runner_picks_up_task(self, teams_root: Path, monkeypatch):
        """Runner 自动领取 TaskList 中的任务并标记 completed。"""
        tm = self._make_teammate("alice", "t1")
        _patch_teammate(monkeypatch, tm, "已完成")
        mb = Mailbox(); tl = TaskList(teams_root, "t1")
        task = tl.create("查询销售数据")

        runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
        runner.start()

        # 等待任务被领取并完成
        for _ in range(40):
            await asyncio.sleep(0.05)
            t = tl.get(task.id)
            if t.status == "completed":
                break
        assert tl.get(task.id).status == "completed"
        assert tl.get(task.id).result == "已完成"

        await runner.request_shutdown()
        await runner.wait_done()

    @pytest.mark.asyncio
    async def test_runner_processes_message(self, teams_root: Path, monkeypatch):
        """Runner 收到普通消息会运行一轮 agent loop。"""
        tm = self._make_teammate("bob", "t1")
        _patch_teammate(monkeypatch, tm, "收到你的消息")
        mb = Mailbox(); tl = TaskList(teams_root, "t1")

        runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
        runner.start()

        await mb.send(Message(sender="leader", to="bob", content="你好"))
        # 等 last_output 被填充
        for _ in range(40):
            await asyncio.sleep(0.05)
            if runner.last_output:
                break
        assert runner.last_output == "收到你的消息"

        await runner.request_shutdown()
        await runner.wait_done()

    @pytest.mark.asyncio
    async def test_runner_shutdown_exits_loop(self, teams_root: Path, monkeypatch):
        """收到 shutdown_request 时 Runner 优雅退出。"""
        tm = self._make_teammate("c", "t1")
        _patch_teammate(monkeypatch, tm, "")
        mb = Mailbox(); tl = TaskList(teams_root, "t1")

        runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
        runner.start()
        await runner.request_shutdown()
        await asyncio.wait_for(runner.wait_done(), timeout=2.0)
        # 退出后从 Mailbox 中注销
        assert "c" not in mb.members()


# ── Team / TeamManager ───────────────────────────────────────────────

class TestTeamLifecycle:
    """Team 容器生命周期与边界规则。"""

    @pytest.mark.asyncio
    async def test_create_and_delete(self, teams_root: Path):
        mgr = TeamManager(teams_root=teams_root)
        team = mgr.create_team("my-team")
        assert mgr.get("my-team") is team
        await mgr.delete_team("my-team")
        assert mgr.get("my-team") is None

    def test_duplicate_team_rejected(self, teams_root: Path):
        mgr = TeamManager(teams_root=teams_root)
        mgr.create_team("dup")
        with pytest.raises(ValueError):
            mgr.create_team("dup")

    @pytest.mark.asyncio
    async def test_delete_with_active_members_rejected(self, teams_root: Path, monkeypatch):
        """有活跃 Teammate 时拒绝普通删除；force=True 才能强制清理。"""
        mgr = TeamManager(teams_root=teams_root)
        team = mgr.create_team("t1")
        tm = Teammate(name="alice", team_name="t1", model=None)
        _patch_teammate(monkeypatch, tm, "")
        team.add_teammate(tm)

        with pytest.raises(RuntimeError):
            await mgr.delete_team("t1")

        # force 后能正常清理
        await mgr.delete_team("t1", force=True)
        assert mgr.get("t1") is None

    @pytest.mark.asyncio
    async def test_teammate_cannot_create_team_or_spawn(self, teams_root: Path):
        """扁平名册：Teammate 不能创建团队或 spawn 其他 Teammate。"""
        mgr = TeamManager(teams_root=teams_root)
        mgr.create_team("t1")
        ctx = TeammateContext("a@t1", "a", "t1", "red")

        async def run_as_teammate():
            with pytest.raises(PermissionError):
                mgr.create_team("from-teammate")
            with pytest.raises(PermissionError):
                mgr.spawn_teammate(
                    "t1",
                    Teammate(name="b", team_name="t1", model=None),
                )

        await run_in_teammate_context(ctx, run_as_teammate)

    @pytest.mark.asyncio
    async def test_cleanup_all(self, teams_root: Path, monkeypatch):
        """cleanup_all 强制清理所有团队。"""
        mgr = TeamManager(teams_root=teams_root)
        for n in ("t1", "t2"):
            mgr.create_team(n)
            tm = Teammate(name="a", team_name=n, model=None)
            _patch_teammate(monkeypatch, tm, "")
            mgr.get(n).add_teammate(tm)
        await mgr.cleanup_all()
        assert mgr.list_teams() == []
