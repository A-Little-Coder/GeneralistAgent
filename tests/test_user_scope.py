"""
user_scope 测试 —— 多 user × 多 session 的核心隔离与切换行为。

覆盖 specs/user-scope/spec.md 的关键 Scenario：
  - 切到不存在的 user 自动 bootstrap session-1
  - 不同 user sessions 互相不可见
  - 同名 session_id 跨 user 独立（alice:session-1 ≠ bob:session-1）
  - compose_thread_id 拼接正确
  - user_id 含冒号 / 空字符 / 拒绝
"""

from pathlib import Path

import pytest

from src.persistence import SessionManager


# ── switch_user 行为 ────────────────────────────────────────────────


class TestSwitchUser:
    def test_switch_user_creates_bucket(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.switch_user("alice")
        sess = sm.bootstrap()
        assert sm.current_user_id == "alice"
        assert sess.id == "session-1"
        assert "alice" in sm.users()

    def test_switch_user_reject_colon(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        with pytest.raises(ValueError, match="冒号"):
            sm.switch_user("alice:bob")

    def test_switch_user_reject_empty(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        with pytest.raises(ValueError):
            sm.switch_user("")
        with pytest.raises(ValueError):
            sm.switch_user("   ")


# ── user 间隔离 ────────────────────────────────────────────────────


class TestUserIsolation:
    def test_users_are_isolated(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)

        sm.switch_user("alice")
        sm.bootstrap()                              # alice / session-1
        alice_s2 = sm.new()                         # alice / session-2
        sm.set_title_if_empty(alice_s2.id, "alice 的话题")

        sm.switch_user("bob")
        sm.bootstrap()
        # bob 看不到 alice 的 sessions
        bob_lists = [s.id for s in sm.list()]
        assert bob_lists == ["session-1"]
        # bob 也没法 switch 到 alice 的 session-2
        with pytest.raises(KeyError):
            sm.switch(alice_s2.id)

        # 切回 alice，看到自己的全部 sessions
        sm.switch_user("alice")
        alice_lists = [s.id for s in sm.list()]
        assert set(alice_lists) == {"session-1", "session-2"}
        assert sm.get("session-2").title == "alice 的话题"

    def test_same_session_id_across_users(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)

        sm.switch_user("alice")
        sm.bootstrap()
        sm.set_title_if_empty("session-1", "alice 张三")

        sm.switch_user("bob")
        sm.bootstrap()
        sm.set_title_if_empty("session-1", "bob 李四")

        # 同名 session-1，但 title 各自独立
        sm.switch_user("alice")
        assert sm.get("session-1").title == "alice 张三"
        sm.switch_user("bob")
        assert sm.get("session-1").title == "bob 李四"


# ── compose_thread_id ─────────────────────────────────────────────


class TestComposeThreadId:
    def test_basic_compose(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.switch_user("alice")
        sm.bootstrap()
        assert sm.compose_thread_id("session-1") == "alice:session-1"

    def test_compose_reflects_current_user(self, tmp_path: Path):
        sm = SessionManager(memory_dir=tmp_path)
        sm.switch_user("alice")
        sm.bootstrap()
        sm.switch_user("bob")
        sm.bootstrap()
        # current 切到 bob 后，拼接也跟着切
        assert sm.compose_thread_id("session-1") == "bob:session-1"


# ── 持久化 + 重启恢复 ──────────────────────────────────────────────


class TestPersistenceAcrossRestart:
    def test_user_buckets_survive_restart(self, tmp_path: Path):
        sm1 = SessionManager(memory_dir=tmp_path)
        sm1.switch_user("alice")
        sm1.bootstrap()
        sm1.new()
        sm1.switch_user("bob")
        sm1.bootstrap()

        # 新实例加载
        sm2 = SessionManager(memory_dir=tmp_path)
        # current_user_id 不持久化，新 SM 默认 'default'
        assert sm2.current_user_id == "default"
        # 但 alice / bob 的桶都还在
        assert set(sm2.users()) == {"alice", "bob"}

        sm2.switch_user("alice")
        assert len(sm2.list()) == 2
        sm2.switch_user("bob")
        assert len(sm2.list()) == 1
