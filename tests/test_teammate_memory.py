"""
Teammate 记忆测试 —— X2 语义（请求内累积；不同 Teammate 互不可见）。

测试关注点：
  - Runner 启动后只构建一次 Agent；后续 turn 复用同一份 agent + MemorySaver
  - 同一 Teammate 多次 _run_one_turn 之间记忆贯穿（验证 thread_id 复用）
  - 不同 Teammate 的 MemorySaver 互相隔离（独立实例）
  - Teammate 不写入 leader.db（不应在某外部 SqliteSaver 留下记录）

策略：用一个记录调用次数的 fake agent，验证 thread_id 一致 / 不同 Runner 不串台。
"""

import asyncio
from pathlib import Path

import pytest

from src.orchestration.context import TeammateContext, assign_color, format_agent_id
from src.orchestration.mailbox import Mailbox, Message
from src.orchestration.runner import Runner
from src.orchestration.task_list import TaskList
from src.orchestration.teammate import Teammate


# ── fake agent：记录每轮的 thread_id 与 prompt ──────────────────────


class _RecordingAgent:
    """记录每轮调用的 thread_id 与 prompt；按预设序列响应。"""

    def __init__(self, replies):
        self._replies = list(replies)
        self._idx = 0
        self.calls = []   # list[(thread_id, prompt)]

    async def astream(self, state, config=None, stream_mode=None):
        from langchain_core.messages import AIMessage

        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
        last_user = state["messages"][-1].content
        self.calls.append((thread_id, last_user))

        reply = self._replies[self._idx] if self._idx < len(self._replies) else "ack"
        self._idx += 1
        yield ("updates", {"call": {"messages": [AIMessage(content=reply)]}})


def _make_teammate(name: str, team: str) -> Teammate:
    """构造一个不依赖真实 LLM 的 Teammate。"""
    return Teammate(name=name, team_name=team, model=None, tools=[])


# ── 1. 同一 Teammate 多次唤起共享 thread_id ────────────────────────


@pytest.mark.asyncio
async def test_same_teammate_reuses_thread_id_across_turns(tmp_path: Path):
    """同一 Runner 处理两条消息 —— thread_id 一致，agent 实例一致。"""
    tm = _make_teammate("alice", "t-mem")
    mb = Mailbox()
    tl = TaskList(base_dir=tmp_path, team_name="t-mem")

    recording = _RecordingAgent(replies=["r1", "r2"])
    tm.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: recording  # type: ignore

    runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
    runner.start()

    # 发两条消息
    await mb.send(Message(sender="leader", to="alice", content="第一条", kind="message"))
    await asyncio.sleep(0.3)
    await mb.send(Message(sender="leader", to="alice", content="第二条", kind="message"))
    await asyncio.sleep(0.5)

    await runner.request_shutdown()
    await runner.wait_done()

    # 至少处理了两条
    assert len(recording.calls) >= 2
    thread_ids = {t for t, _ in recording.calls}
    # 两次都用同一个 thread_id（=teammate_id）
    assert len(thread_ids) == 1
    assert thread_ids.pop() == tm.context.teammate_id


# ── 2. Runner 启动后只构建一次 agent ───────────────────────────────


@pytest.mark.asyncio
async def test_runner_builds_agent_only_once(tmp_path: Path):
    """build_agent_for_prompt 在 Runner 生命周期内只被调用一次。"""
    tm = _make_teammate("once", "t-once")
    mb = Mailbox()
    tl = TaskList(base_dir=tmp_path, team_name="t-once")

    build_count = {"n": 0}
    recording = _RecordingAgent(replies=["r1", "r2", "r3"])

    def fake_build(base_prompt: str = "", checkpointer=None):
        build_count["n"] += 1
        return recording

    tm.build_agent_for_prompt = fake_build  # type: ignore

    runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
    runner.start()

    for content in ("a", "b", "c"):
        await mb.send(Message(sender="leader", to="once", content=content, kind="message"))
        await asyncio.sleep(0.15)

    await runner.request_shutdown()
    await runner.wait_done()

    assert build_count["n"] == 1, f"Runner 应只构建一次 agent，实际 {build_count['n']} 次"
    assert len(recording.calls) >= 3


# ── 3. 不同 Teammate MemorySaver 互不可见 ──────────────────────────


@pytest.mark.asyncio
async def test_different_teammates_have_independent_memory_savers(tmp_path: Path):
    """两个 Runner 的 MemorySaver 是不同实例。"""
    a = _make_teammate("alice", "t-iso")
    b = _make_teammate("bob", "t-iso")
    mb = Mailbox()
    tl = TaskList(base_dir=tmp_path, team_name="t-iso")

    ra = Runner(teammate=a, mailbox=mb, task_list=tl, idle_interval=0.1)
    rb = Runner(teammate=b, mailbox=mb, task_list=tl, idle_interval=0.1)

    # 各自独立的 MemorySaver
    assert ra._memory_saver is not rb._memory_saver
    # thread_id 也不同
    assert a.context.teammate_id != b.context.teammate_id


# ── 4. Teammate 不写入外部 SqliteSaver（leader.db） ────────────────


@pytest.mark.asyncio
async def test_teammate_does_not_pollute_leader_db(tmp_path: Path):
    """LeaderStore 不应出现 Teammate 的 thread_id。"""
    from src.persistence import LeaderStore

    store = await LeaderStore.create(memory_dir=tmp_path)
    try:
        tm = _make_teammate("alice", "t-iso2")
        mb = Mailbox()
        tl = TaskList(base_dir=tmp_path / "teams", team_name="t-iso2")

        recording = _RecordingAgent(replies=["x"])
        tm.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: recording  # type: ignore

        runner = Runner(teammate=tm, mailbox=mb, task_list=tl, idle_interval=0.05)
        runner.start()

        await mb.send(Message(sender="leader", to="alice", content="hi", kind="message"))
        await asyncio.sleep(0.3)

        await runner.request_shutdown()
        await runner.wait_done()

        # leader.db 应不含 teammate 的 thread_id
        assert tm.context.teammate_id not in await store.list_thread_ids()
    finally:
        await store.aclose()
