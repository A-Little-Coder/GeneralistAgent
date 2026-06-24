"""
cleanup_spawned_in_turn 测试 —— 焚毁本轮新建的 Teammate。

测试关注点：
  - spawn 一个 Teammate 后，本轮 set 包含它
  - cleanup_spawned_in_turn 后该 Teammate.Runner.task.done() 为 True
  - 集合在 cleanup 后清空
  - cleanup 失败的 Teammate 不阻塞其他 Teammate 被清理
"""

import asyncio
from pathlib import Path

import pytest

from src.orchestration.mailbox import Message
from src.orchestration.team import TeamManager
from src.orchestration.teammate import Teammate


def _make_teammate(name: str, team: str) -> Teammate:
    return Teammate(name=name, team_name=team, model=None, tools=[])


# ── 基础 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spawned_this_turn_tracked(tmp_path: Path):
    tm_mgr = TeamManager(teams_root=tmp_path / "teams")
    tm_mgr.create_team("main")

    alice = _make_teammate("alice", "main")
    bob = _make_teammate("bob", "main")
    # 替换 build_agent_for_prompt 避免真打 LLM
    alice.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore
    bob.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore

    tm_mgr.spawn_teammate("main", alice)
    tm_mgr.spawn_teammate("main", bob)

    assert ("main", "alice") in tm_mgr.spawned_this_turn
    assert ("main", "bob") in tm_mgr.spawned_this_turn
    assert len(tm_mgr.spawned_this_turn) == 2


@pytest.mark.asyncio
async def test_cleanup_spawned_in_turn_shuts_down_and_clears(tmp_path: Path):
    tm_mgr = TeamManager(teams_root=tmp_path / "teams")
    tm_mgr.create_team("main")

    alice = _make_teammate("alice", "main")
    bob = _make_teammate("bob", "main")
    alice.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore
    bob.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore

    ra = tm_mgr.spawn_teammate("main", alice)
    rb = tm_mgr.spawn_teammate("main", bob)

    # 给 Runner 一点时间进入 idle 循环
    await asyncio.sleep(0.1)

    cleaned = await tm_mgr.cleanup_spawned_in_turn()
    assert cleaned == 2

    # Runner.task 应完成
    assert ra._task is not None and ra._task.done()
    assert rb._task is not None and rb._task.done()

    # 团队名册里也清掉了
    team = tm_mgr.get("main")
    assert "alice" not in team.members
    assert "bob" not in team.members

    # 集合被清空
    assert len(tm_mgr.spawned_this_turn) == 0


@pytest.mark.asyncio
async def test_cleanup_idempotent_when_no_spawn(tmp_path: Path):
    tm_mgr = TeamManager(teams_root=tmp_path / "teams")
    tm_mgr.create_team("main")
    cleaned = await tm_mgr.cleanup_spawned_in_turn()
    assert cleaned == 0


@pytest.mark.asyncio
async def test_two_rounds_independent(tmp_path: Path):
    """第二轮 spawn 后不再包含上轮已 cleanup 的 Teammate。"""
    tm_mgr = TeamManager(teams_root=tmp_path / "teams")
    tm_mgr.create_team("main")

    # 第一轮
    a1 = _make_teammate("alice", "main")
    a1.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore
    tm_mgr.spawn_teammate("main", a1)
    await asyncio.sleep(0.1)
    await tm_mgr.cleanup_spawned_in_turn()
    assert len(tm_mgr.spawned_this_turn) == 0

    # 第二轮：同名 Teammate
    a2 = _make_teammate("alice", "main")
    a2.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _SilentAgent()  # type: ignore
    r2 = tm_mgr.spawn_teammate("main", a2)
    assert tm_mgr.spawned_this_turn == {("main", "alice")}
    assert r2 is not None

    await tm_mgr.cleanup_spawned_in_turn()


# ── fake agent：永远等待，不主动结束 ───────────────────────────────


class _SilentAgent:
    """什么都不返回的 fake agent；让 Runner 留在 idle 循环里。"""
    async def astream(self, state, config=None, stream_mode=None):
        if False:
            yield  # 让其为 async generator
