"""
SessionManager —— 多 user × 多 session 元数据管理，存于 `memory/sessions.json`。

数据模型（add-user-scope-to-memory）：

    {
      "users": {
        "alice": {
          "current": "session-2",
          "sessions": [{id, title, created_at, last_active_at}, ...]
        },
        "default": { ... }
      }
    }

SessionManager 持有 `current_user_id` 状态，所有公共方法（list / new / switch /
delete / rename / set_title_if_empty / bootstrap）隐式作用于该 user。

CLI 启动时 `input()` 拿到 user_id 后调 `switch_user(uid)`；运行中 `/user <uid>`
也调同一接口。

`current_user_id` **不持久化** —— 每次启动由 CLI 决定（避免"上次 alice，下次默认还是
alice"的隐式行为）。

迁移：检测旧格式（无 `users` 字段）→ 自动包到 `users.default` 并落盘。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from src.persistence.user_migration import (
    empty_users_dict,
    migrate_legacy_sessions_dict,
)

if TYPE_CHECKING:
    from src.persistence.leader_store import LeaderStore


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DIR = _PROJECT_ROOT / "memory"
DEFAULT_SESSIONS_FILENAME = "sessions.json"
DEFAULT_USER_ID = "default"

# 标题截取的字符数上限（中文按 Unicode 字符）
_TITLE_MAX_CHARS = 20


def _now_iso() -> str:
    """UTC ISO 8601 时间戳（不带毫秒，便于 JSON 直观）。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_session_id(existing_ids: set[str]) -> str:
    """生成下一个 session id：session-1 / session-2 …，跳过已存在的。"""
    i = 1
    while True:
        candidate = f"session-{i}"
        if candidate not in existing_ids:
            return candidate
        i += 1


@dataclass
class Session:
    """单个会话的元数据。"""
    id: str
    title: str = ""
    created_at: str = field(default_factory=_now_iso)
    last_active_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            created_at=d.get("created_at", _now_iso()),
            last_active_at=d.get("last_active_at", _now_iso()),
        )


@dataclass
class _UserBucket:
    """单个 user 的 sessions 状态。"""
    current: Optional[str] = None
    sessions: list[Session] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "sessions": [s.to_dict() for s in self.sessions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "_UserBucket":
        sessions = [Session.from_dict(x) for x in d.get("sessions", []) if isinstance(x, dict)]
        current = d.get("current") if d.get("current") in {s.id for s in sessions} else (
            sessions[0].id if sessions else None
        )
        return cls(current=current, sessions=sessions)


class SessionManager:
    """多 user × 多 session 元数据管理。

    用法：
        sm = SessionManager()
        sm.switch_user("alice")            # 输入或运行时切换；首次会自动建桶
        sm.bootstrap()                     # 当前 user 无 session 时自动建 session-1
        current = sm.get_current()
        sm.new() / sm.switch(id) / sm.rename(id, title)
        await sm.delete(id, leader_store)  # 联动清 checkpoint，用复合 thread_id

        # 拼 LangGraph thread_id（CLI 用这个传给 astream）
        thread_id = sm.compose_thread_id(current.id)   # → "alice:session-2"
    """

    def __init__(
        self,
        file_path: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
        default_user_id: str = DEFAULT_USER_ID,
    ):
        if file_path is not None:
            self._file = Path(file_path)
        else:
            base = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
            self._file = base / DEFAULT_SESSIONS_FILENAME
        self._file.parent.mkdir(parents=True, exist_ok=True)

        self._users: dict[str, _UserBucket] = {}
        # current_user_id 不持久化；CLI 启动 input 决定，运行中 /user 修改
        self._current_user_id: str = default_user_id
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────────

    def _load(self) -> None:
        """从磁盘加载；检测旧格式自动迁移到 users.default 并落盘。"""
        if not self._file.exists():
            return

        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 文件损坏：保留磁盘原样，内存视为空；调用方应 bootstrap 重新建
            return

        data, migrated = migrate_legacy_sessions_dict(raw, default_user_id=DEFAULT_USER_ID)

        users_raw = data.get("users", {})
        if not isinstance(users_raw, dict):
            users_raw = {}

        self._users = {
            uid: _UserBucket.from_dict(bucket if isinstance(bucket, dict) else {})
            for uid, bucket in users_raw.items()
        }

        # 旧格式迁移完立即落盘，避免下次启动再迁
        if migrated:
            self._save()

    def _save(self) -> None:
        """原子写：tempfile + os.replace，避免半成品文件。"""
        payload = {
            "users": {uid: bucket.to_dict() for uid, bucket in self._users.items()},
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".sessions.", suffix=".json.tmp", dir=str(self._file.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, self._file)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── user 切换 ──────────────────────────────────────────────────

    def switch_user(self, user_id: str) -> str:
        """切换当前 user_id。新 user 自动建空桶（不 bootstrap session，由调用方决定）。

        Args:
            user_id: 目标 user_id；不允许含冒号

        Returns:
            生效的 user_id

        Raises:
            ValueError: user_id 含冒号
        """
        if ":" in user_id:
            raise ValueError(f"user_id 不允许包含冒号: {user_id!r}")
        if user_id.strip() == "":
            raise ValueError("user_id 不能为空")

        if user_id not in self._users:
            self._users[user_id] = _UserBucket()
            self._save()
        self._current_user_id = user_id
        return user_id

    @property
    def current_user_id(self) -> str:
        return self._current_user_id

    def users(self) -> list[str]:
        """列出已存在的 user_id —— 仅调试用。"""
        return list(self._users.keys())

    def _bucket(self) -> _UserBucket:
        """取当前 user 的桶；不存在时按 switch_user 语义建空桶。"""
        if self._current_user_id not in self._users:
            self._users[self._current_user_id] = _UserBucket()
        return self._users[self._current_user_id]

    # ── 首启 ────────────────────────────────────────────────────────

    def bootstrap(self) -> Session:
        """若当前 user 无 session，自动建 session-1 并设为该 user 的 current。"""
        bucket = self._bucket()
        if not bucket.sessions:
            sess = Session(id="session-1")
            bucket.sessions.append(sess)
            bucket.current = sess.id
            self._save()
        elif bucket.current is None:
            bucket.current = bucket.sessions[0].id
            self._save()
        return self.get_current()  # type: ignore[return-value]

    # ── 查询（隐式作用于 current user）─────────────────────────────

    def list(self) -> list[Session]:
        return list(self._bucket().sessions)

    def get(self, session_id: str) -> Optional[Session]:
        for s in self._bucket().sessions:
            if s.id == session_id:
                return s
        return None

    def get_current(self) -> Optional[Session]:
        bucket = self._bucket()
        if bucket.current is None:
            return None
        return self.get(bucket.current)

    @property
    def current_id(self) -> Optional[str]:
        return self._bucket().current

    # ── 复合 thread_id ────────────────────────────────────────────

    def compose_thread_id(self, session_id: str) -> str:
        """拼成 LangGraph 用的 thread_id：`<current_user_id>:<session_id>`。

        给 CLI 在 `agent.astream` / `LeaderStore.purge` 处使用。
        """
        return f"{self._current_user_id}:{session_id}"

    # ── 变更（隐式作用于 current user）─────────────────────────────

    def new(self, title: str = "") -> Session:
        """新建空 session 并切换为当前 user 的 current。"""
        bucket = self._bucket()
        ids = {s.id for s in bucket.sessions}
        sess = Session(id=_next_session_id(ids), title=title)
        bucket.sessions.append(sess)
        bucket.current = sess.id
        self._save()
        return sess

    def switch(self, session_id: str) -> Session:
        """切换当前 user 的 current session。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在于 user '{self._current_user_id}'")
        bucket = self._bucket()
        bucket.current = target.id
        target.last_active_at = _now_iso()
        self._save()
        return target

    async def delete(
        self,
        session_id: str,
        leader_store: Optional["LeaderStore"] = None,
    ) -> Session:
        """删除当前 user 的某 session，联动清复合 thread_id 的 checkpoint。

        删除的若是 current → 自动切到剩余首个；若空则新建 session-1。
        """
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在于 user '{self._current_user_id}'")

        if leader_store is not None:
            # 用复合 thread_id 清 —— add-user-scope-to-memory 后正确做法
            await leader_store.purge(self.compose_thread_id(session_id))

        bucket = self._bucket()
        bucket.sessions = [s for s in bucket.sessions if s.id != session_id]

        if bucket.current == session_id:
            if bucket.sessions:
                bucket.current = bucket.sessions[0].id
            else:
                new_sess = Session(id="session-1")
                bucket.sessions.append(new_sess)
                bucket.current = new_sess.id

        self._save()
        return target

    def rename(self, session_id: str, new_title: str) -> Session:
        """改标题（用户主动 /title，强制覆盖）。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在于 user '{self._current_user_id}'")
        target.title = new_title.strip()
        self._save()
        return target

    def set_title_if_empty(self, session_id: str, user_input: str) -> Session:
        """自动取标题：仅当 title 为空时基于 user_input 前 20 字生成。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在于 user '{self._current_user_id}'")

        target.last_active_at = _now_iso()

        if target.title.strip() == "":
            text = user_input.strip()
            if len(text) > _TITLE_MAX_CHARS:
                target.title = text[:_TITLE_MAX_CHARS] + "…"
            else:
                target.title = text
        self._save()
        return target

    def touch(self, session_id: str) -> Session:
        """刷新 last_active_at（不动 title）。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在于 user '{self._current_user_id}'")
        target.last_active_at = _now_iso()
        self._save()
        return target

    # ── 调试 ────────────────────────────────────────────────────────

    @property
    def file_path(self) -> Path:
        return self._file
