"""
user_migration 测试 —— 两个迁移路径的幂等性与正确性。

测试矩阵：
  - sessions.json 旧格式 → 新格式 + 落盘 + 不二次迁
  - leader.db 中无冒号 thread_id → 加 'default:' 前缀 + 幂等 + 事务回滚
"""

import json
from pathlib import Path

import aiosqlite
import pytest

from src.persistence import LeaderStore, SessionManager
from src.persistence.session_manager import DEFAULT_USER_ID
from src.persistence.user_migration import (
    empty_users_dict,
    migrate_legacy_sessions_dict,
    migrate_legacy_thread_ids,
)


# ── sessions.json 迁移 ──────────────────────────────────────────────


class TestSessionsJsonMigration:
    def test_legacy_format_migrated(self):
        legacy = {
            "current": "session-2",
            "sessions": [
                {"id": "session-1", "title": "A", "created_at": "x", "last_active_at": "x"},
                {"id": "session-2", "title": "B", "created_at": "y", "last_active_at": "y"},
            ],
        }
        new, migrated = migrate_legacy_sessions_dict(legacy)
        assert migrated
        assert "users" in new
        assert "default" in new["users"]
        assert new["users"]["default"]["current"] == "session-2"
        assert len(new["users"]["default"]["sessions"]) == 2

    def test_new_format_no_op(self):
        new_format = {
            "users": {"alice": {"current": "session-1", "sessions": []}}
        }
        result, migrated = migrate_legacy_sessions_dict(new_format)
        assert not migrated
        assert result is new_format

    def test_empty_dict_returns_empty_new_format(self):
        result, migrated = migrate_legacy_sessions_dict({})
        # 空 dict 视为损坏旧文件，包装成 default 桶
        assert migrated
        assert "users" in result
        assert "default" in result["users"]

    def test_non_dict_input_safe(self):
        result, migrated = migrate_legacy_sessions_dict("not a dict")
        assert not migrated
        assert result == {"users": {}}

    def test_session_manager_migrates_and_saves(self, tmp_path: Path):
        """端到端：在磁盘放旧格式 → SessionManager 加载 → 自动落盘新格式。"""
        file_path = tmp_path / "sessions.json"
        file_path.write_text(json.dumps({
            "current": "session-1",
            "sessions": [{"id": "session-1", "title": "旧", "created_at": "x", "last_active_at": "x"}],
        }), encoding="utf-8")

        sm = SessionManager(memory_dir=tmp_path)
        # 旧格式已转新格式，落到 default 桶
        sm.switch_user("default")
        assert sm.get("session-1") is not None
        assert sm.get("session-1").title == "旧"

        # 重新读磁盘，确认已写回新格式
        on_disk = json.loads(file_path.read_text(encoding="utf-8"))
        assert "users" in on_disk
        assert "default" in on_disk["users"]


# ── leader.db thread_id 迁移 ───────────────────────────────────────


class TestLeaderDbMigration:
    @pytest.mark.asyncio
    async def test_legacy_thread_ids_migrated(self, tmp_path: Path):
        db_path = tmp_path / "leader.db"

        # 先建一个有旧 thread_id 的库 —— 用 LeaderStore.create 建表，但直接写裸 thread_id
        store = await LeaderStore.create(db_path=db_path)
        try:
            saver = store.get_checkpointer()
            await saver.aput(
                {"configurable": {"thread_id": "session-legacy", "checkpoint_ns": ""}},
                {
                    "v": 4, "id": "c1", "ts": "2026-06-23T00:00:00Z",
                    "channel_values": {}, "channel_versions": {},
                    "versions_seen": {}, "pending_sends": [],
                },
                {"source": "test", "step": 1, "parents": {}},
                {},
            )
            # 模拟人为遗留：上面写的会被 setup() 时的迁移改名 → 用直接 SQL 把它改回无冒号
            await store._conn.execute(
                "UPDATE checkpoints SET thread_id = 'session-legacy' WHERE thread_id LIKE 'default:%'"
            )
            await store._conn.execute(
                "UPDATE writes SET thread_id = 'session-legacy' WHERE thread_id LIKE 'default:%'"
            )
            await store._conn.commit()
            ids = await store.list_thread_ids()
            assert "session-legacy" in ids
        finally:
            await store.aclose()

        # 再 setup 应该把它改名
        store2 = await LeaderStore.create(db_path=db_path)
        try:
            ids = await store2.list_thread_ids()
            assert "session-legacy" not in ids
            assert "default:session-legacy" in ids
        finally:
            await store2.aclose()

    @pytest.mark.asyncio
    async def test_migration_idempotent(self, tmp_path: Path):
        """迁过的库再启动不动。"""
        db_path = tmp_path / "leader.db"

        # 第一次：什么都没写，setup 建表后里面没旧数据
        store1 = await LeaderStore.create(db_path=db_path)
        try:
            await store1.list_thread_ids()
        finally:
            await store1.aclose()

        # 直接调迁移函数应该返回 0
        conn = await aiosqlite.connect(str(db_path))
        try:
            affected = await migrate_legacy_thread_ids(conn)
            assert affected == 0
        finally:
            await conn.close()

    @pytest.mark.asyncio
    async def test_migration_transaction_rollback(self, tmp_path: Path, monkeypatch):
        """迁移中失败 → 事务回滚，数据保持迁移前。"""
        db_path = tmp_path / "leader.db"

        # 用真实 saver 建表 + 写旧 thread_id
        store = await LeaderStore.create(db_path=db_path)
        try:
            saver = store.get_checkpointer()
            await saver.aput(
                {"configurable": {"thread_id": "row-x", "checkpoint_ns": ""}},
                {
                    "v": 4, "id": "c1", "ts": "2026-06-23T00:00:00Z",
                    "channel_values": {}, "channel_versions": {},
                    "versions_seen": {}, "pending_sends": [],
                },
                {"source": "test", "step": 1, "parents": {}},
                {},
            )
            # setup() 已经迁过一次了，把它改回无冒号方便复现
            await store._conn.execute(
                "UPDATE checkpoints SET thread_id = 'row-x' WHERE thread_id = 'default:row-x'"
            )
            await store._conn.execute(
                "UPDATE writes SET thread_id = 'row-x' WHERE thread_id = 'default:row-x'"
            )
            await store._conn.commit()
        finally:
            await store.aclose()

        # 模拟迁移过程失败
        conn = await aiosqlite.connect(str(db_path))
        try:
            # monkeypatch conn.commit → 抛异常
            original_commit = conn.commit

            async def boom():
                raise RuntimeError("强制失败")

            conn.commit = boom  # type: ignore

            with pytest.raises(RuntimeError, match="强制失败"):
                await migrate_legacy_thread_ids(conn)

            conn.commit = original_commit  # type: ignore

            # 验证回滚：row-x 还是无冒号
            cur = await conn.execute("SELECT thread_id FROM checkpoints WHERE thread_id LIKE '%row-x'")
            rows = [r[0] for r in await cur.fetchall()]
            await cur.close()
            assert rows == ["row-x"]
        finally:
            await conn.close()


# ── 空格式辅助 ──────────────────────────────────────────────────────


class TestEmptyUsersDict:
    def test_shape(self):
        d = empty_users_dict()
        assert d == {"users": {}}
