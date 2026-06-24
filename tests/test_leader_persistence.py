"""
LeaderStore 测试 —— 覆盖 AsyncSqliteSaver 持久化、跨进程恢复、purge。

测试策略：
  - 用 tmp_path 隔离每个 case 的数据库
  - 跨进程恢复用"新建 store 实例 → 读出之前写入的 checkpoint"模拟
  - 不依赖真实 LLM；直接调 AsyncSqliteSaver 的 aput / aget_tuple API
"""

from pathlib import Path

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.persistence import LeaderStore


# ── 基础 ─────────────────────────────────────────────────────────────


class TestLeaderStoreBasics:
    @pytest.mark.asyncio
    async def test_auto_create_memory_dir_and_db(self, tmp_path: Path):
        mem = tmp_path / "memory-x"
        assert not mem.exists()
        store = await LeaderStore.create(memory_dir=mem)
        try:
            assert mem.exists()
            assert (mem / "leader.db").exists()
            assert isinstance(store.get_checkpointer(), BaseCheckpointSaver)
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_custom_db_path(self, tmp_path: Path):
        custom = tmp_path / "deep/nested/custom.db"
        store = await LeaderStore.create(db_path=custom)
        try:
            assert custom.exists()
            assert store.db_path == custom
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, tmp_path: Path):
        store = await LeaderStore.create(memory_dir=tmp_path)
        await store.aclose()
        await store.aclose()

    @pytest.mark.asyncio
    async def test_get_checkpointer_before_setup_raises(self, tmp_path: Path):
        store = LeaderStore(memory_dir=tmp_path)
        with pytest.raises(RuntimeError):
            store.get_checkpointer()


# ── 跨进程恢复 ───────────────────────────────────────────────────────


class TestCrossProcessRecovery:
    """模拟"写入 → 关 store → 重新打开 → 历史恢复"流程。"""

    async def _write_checkpoint(self, store: LeaderStore, thread_id: str, msg: str) -> None:
        """通过 AsyncSqliteSaver.aput 直接写一个最小 checkpoint。"""
        saver = store.get_checkpointer()
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint = {
            "v": 4,
            "id": f"ckpt-{thread_id}-{msg}",
            "ts": "2026-06-23T00:00:00Z",
            "channel_values": {"messages": [{"content": msg, "type": "human"}]},
            "channel_versions": {"messages": 1},
            "versions_seen": {},
            "pending_sends": [],
        }
        metadata = {"source": "test", "step": 1, "parents": {}}
        await saver.aput(config, checkpoint, metadata, {})

    @pytest.mark.asyncio
    async def test_write_close_reopen_recover(self, tmp_path: Path):
        store1 = await LeaderStore.create(memory_dir=tmp_path)
        try:
            await self._write_checkpoint(store1, "sess-A", "你好")
        finally:
            await store1.aclose()

        # 模拟新进程：重新打开同一目录
        store2 = await LeaderStore.create(memory_dir=tmp_path)
        try:
            cp = await store2.get_checkpointer().aget_tuple(
                {"configurable": {"thread_id": "sess-A", "checkpoint_ns": ""}}
            )
            assert cp is not None
            channels = cp.checkpoint.get("channel_values", {})
            msgs = channels.get("messages", [])
            assert any("你好" in m.get("content", "") for m in msgs)
        finally:
            await store2.aclose()

    @pytest.mark.asyncio
    async def test_multiple_thread_ids_isolated(self, tmp_path: Path):
        store = await LeaderStore.create(memory_dir=tmp_path)
        try:
            await self._write_checkpoint(store, "sess-A", "Alice")
            await self._write_checkpoint(store, "sess-B", "Bob")

            ids = set(await store.list_thread_ids())
            assert {"sess-A", "sess-B"}.issubset(ids)
        finally:
            await store.aclose()


# ── purge ────────────────────────────────────────────────────────────


class TestPurge:
    async def _write(self, store: LeaderStore, thread_id: str) -> None:
        saver = store.get_checkpointer()
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        checkpoint = {
            "v": 4,
            "id": f"ckpt-{thread_id}",
            "ts": "2026-06-23T00:00:00Z",
            "channel_values": {"messages": []},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }
        await saver.aput(config, checkpoint, {"source": "test", "step": 1, "parents": {}}, {})

    @pytest.mark.asyncio
    async def test_purge_removes_only_target_thread(self, tmp_path: Path):
        store = await LeaderStore.create(memory_dir=tmp_path)
        try:
            await self._write(store, "sess-A")
            await self._write(store, "sess-B")
            assert "sess-A" in await store.list_thread_ids()

            await store.purge("sess-A")

            ids = await store.list_thread_ids()
            assert "sess-A" not in ids
            assert "sess-B" in ids
        finally:
            await store.aclose()

    @pytest.mark.asyncio
    async def test_purge_nonexistent_thread_is_noop(self, tmp_path: Path):
        store = await LeaderStore.create(memory_dir=tmp_path)
        try:
            await store.purge("never-existed")
            assert await store.list_thread_ids() == []
        finally:
            await store.aclose()
