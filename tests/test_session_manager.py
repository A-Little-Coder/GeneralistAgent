"""
SessionManager 测试 —— 覆盖 bootstrap / CRUD / 标题策略 / 持久化。
"""

import json
from pathlib import Path

import pytest

from src.persistence import LeaderStore, SessionManager
from src.persistence.session_manager import Session


# ── bootstrap ────────────────────────────────────────────────────────


class TestBootstrap:
    def test_bootstrap_empty_creates_session_1(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        assert sm.list() == []
        current = sm.bootstrap()
        assert current.id == "session-1"
        assert sm.current_id == "session-1"
        # 落盘
        assert (tmp_path / "sessions.json").exists()

    def test_bootstrap_preserves_existing(self, tmp_path: Path):
        # 先写一个文件
        path = tmp_path / "sessions.json"
        path.write_text(json.dumps({
            "current": "session-2",
            "sessions": [
                {"id": "session-1", "title": "旧", "created_at": "2026-01-01", "last_active_at": "2026-01-01"},
                {"id": "session-2", "title": "新", "created_at": "2026-01-02", "last_active_at": "2026-01-02"},
            ],
        }), encoding="utf-8")

        sm = SessionManager(memory_dir=tmp_path)
        current = sm.bootstrap()
        assert current.id == "session-2"
        assert len(sm.list()) == 2

    def test_bootstrap_repairs_dangling_current(self, tmp_path: Path):
        path = tmp_path / "sessions.json"
        path.write_text(json.dumps({
            "current": "session-missing",   # 指向不存在的
            "sessions": [{"id": "session-1", "title": "T", "created_at": "x", "last_active_at": "x"}],
        }), encoding="utf-8")
        sm = SessionManager(memory_dir=tmp_path)
        # _load 校正为第一个
        assert sm.current_id == "session-1"


# ── CRUD ─────────────────────────────────────────────────────────────


class TestCRUD:
    def test_new_creates_and_switches(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        first = sm.current_id

        new = sm.new()
        assert new.id != first
        assert sm.current_id == new.id

    def test_new_generates_sequential_ids(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        s2 = sm.new()
        s3 = sm.new()
        assert s2.id == "session-2"
        assert s3.id == "session-3"

    def test_list_returns_copy(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        lst1 = sm.list()
        lst1.clear()
        # 外部清空不影响内部
        assert len(sm.list()) >= 1

    def test_switch_existing(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        s2 = sm.new()
        sm.switch("session-1")
        assert sm.current_id == "session-1"
        sm.switch(s2.id)
        assert sm.current_id == s2.id

    def test_switch_unknown_raises(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        with pytest.raises(KeyError):
            sm.switch("session-999")

    def test_rename(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        sm.rename("session-1", "我的新标题")
        assert sm.get("session-1").title == "我的新标题"


# ── delete + 联动 LeaderStore.purge ──────────────────────────────────


class TestDelete:
    def test_delete_other_session(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()                  # session-1 (current)
        s2 = sm.new()                   # session-2 (current)
        sm.switch("session-1")          # current → session-1
        import asyncio
        asyncio.run(sm.delete(s2.id))
        assert sm.get(s2.id) is None
        assert sm.current_id == "session-1"

    def test_delete_current_switches_to_first_remaining(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()                  # session-1
        sm.new()                        # session-2 (current)
        import asyncio
        asyncio.run(sm.delete("session-2"))
        assert sm.current_id == "session-1"

    def test_delete_last_creates_session_1_again(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()                  # session-1 only
        import asyncio
        asyncio.run(sm.delete("session-1"))
        assert sm.current_id == "session-1"
        assert len(sm.list()) == 1

    @pytest.mark.asyncio
    async def test_delete_with_leader_store_purge(self, tmp_path: Path):
        store = await LeaderStore.create(memory_dir=tmp_path)
        try:
            sm = SessionManager(memory_dir=tmp_path)
            sm.bootstrap()
            s2 = sm.new()
            # 写一个假 checkpoint 给 s2
            saver = store.get_checkpointer()
            await saver.aput(
                {"configurable": {"thread_id": s2.id, "checkpoint_ns": ""}},
                {
                    "v": 4, "id": "c1", "ts": "2026-06-23T00:00:00Z",
                    "channel_values": {}, "channel_versions": {},
                    "versions_seen": {}, "pending_sends": [],
                },
                {"source": "test", "step": 1, "parents": {}},
                {},
            )
            assert s2.id in await store.list_thread_ids()

            await sm.delete(s2.id, leader_store=store)
            assert s2.id not in await store.list_thread_ids()
        finally:
            await store.aclose()


# ── set_title_if_empty ───────────────────────────────────────────────


class TestTitleStrategy:
    def test_short_title_no_truncate(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        sm.set_title_if_empty("session-1", "你好")
        assert sm.get("session-1").title == "你好"

    def test_long_title_truncated(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        long_text = "查询近七天华东大区按产品分类汇总的销售额并按渠道拆分明细"  # > 20 chars
        sm.set_title_if_empty("session-1", long_text)
        title = sm.get("session-1").title
        assert title.endswith("…")
        assert len(title) == 21  # 20 + 省略号

    def test_existing_title_not_overwritten(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        sm.set_title_if_empty("session-1", "首轮标题")
        sm.set_title_if_empty("session-1", "第二轮不应覆盖")
        assert sm.get("session-1").title == "首轮标题"

    def test_strip_whitespace(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        sm.set_title_if_empty("session-1", "   ABC   ")
        assert sm.get("session-1").title == "ABC"


# ── 持久化（原子写） ─────────────────────────────────────────────────


class TestPersistence:
    def test_atomic_write_no_partial_file(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.bootstrap()
        sm.new()
        # 不应留下任何 .tmp 文件
        leftover = list(tmp_path.glob(".sessions.*.json.tmp"))
        assert leftover == []

    def test_load_corrupt_file_is_safe(self, tmp_path: Path):
        path = tmp_path / "sessions.json"
        path.write_text("this is not json", encoding="utf-8")
        sm = SessionManager(memory_dir=tmp_path)
        # 损坏文件 → 内存视为空，bootstrap 重建
        sm.bootstrap()
        assert sm.current_id == "session-1"

    def test_reload_after_save(self, tmp_path: Path):
        sm1 = SessionManager(memory_dir=tmp_path)
        sm1.bootstrap()
        sm1.set_title_if_empty("session-1", "持久化标题")
        sm1.new()

        sm2 = SessionManager(memory_dir=tmp_path)
        assert sm2.current_id == "session-2"
        assert sm2.get("session-1").title == "持久化标题"
