"""
SessionManager —— 维护 Leader 的多会话元数据，存储于 `memory/sessions.json`。

设计要点：
  - 文件存储而非 SQLite —— 量级小（百级）、人类可读、易调试
  - 原子写：`tempfile + os.replace`，避免崩溃中态
  - 双向联动 LeaderStore：删除 session 时调 LeaderStore.purge 同步清 checkpoint
  - 首启 bootstrap：sessions.json 不存在或空列表时自动建 session-1
  - 标题策略：set_title_if_empty 取首条消息前 20 个 Unicode 字符；后续永不更新（用户可用 /title 改）

非目标：
  - 不实现并发多用户（单 CLI 进程模型）
  - 不实现软删除 / 回收站（首版从简）
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.persistence.leader_store import LeaderStore


# 与 leader_store 同目录，但解耦：SessionManager 不强依赖 LeaderStore 存在
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DIR = _PROJECT_ROOT / "memory"
DEFAULT_SESSIONS_FILENAME = "sessions.json"

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
    title: str = ""                  # 空字符串表示"未命名"，首条消息会自动填充
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


class SessionManager:
    """Session CRUD + current 指针 + 与 LeaderStore 的删除联动。

    用法：
        sm = SessionManager()           # 默认 memory/sessions.json
        sm.bootstrap()                  # 首启自动建 session-1
        current = sm.get_current()
        sm.set_title_if_empty(current.id, user_input)
        sm.new()                        # /new
        sm.list()                       # /sessions
        sm.switch("session-2")          # /switch
        sm.delete("session-2", leader_store=store)  # /delete
        sm.rename("session-1", "Q1 销售")           # /title
    """

    def __init__(
        self,
        file_path: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
    ):
        if file_path is not None:
            self._file = Path(file_path)
        else:
            base = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
            self._file = base / DEFAULT_SESSIONS_FILENAME
        self._file.parent.mkdir(parents=True, exist_ok=True)

        self._sessions: list[Session] = []
        self._current_id: Optional[str] = None
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────────

    def _load(self) -> None:
        """从磁盘加载；文件不存在/损坏视为空状态（待 bootstrap 创建）。"""
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 文件损坏：保留磁盘原样，内存视为空；调用方应 bootstrap 重新建
            return

        raw_sessions = data.get("sessions", [])
        self._sessions = [Session.from_dict(d) for d in raw_sessions]
        self._current_id = data.get("current")
        # 校正 current：若指向不存在的 id，重置为第一个或 None
        ids = {s.id for s in self._sessions}
        if self._current_id not in ids:
            self._current_id = self._sessions[0].id if self._sessions else None

    def _save(self) -> None:
        """原子写：tempfile + os.replace，避免半成品文件。"""
        payload = {
            "current": self._current_id,
            "sessions": [s.to_dict() for s in self._sessions],
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2)

        # 同目录下创建临时文件再 os.replace 保证原子性（跨盘 rename 不可靠）
        fd, tmp_path = tempfile.mkstemp(
            prefix=".sessions.", suffix=".json.tmp", dir=str(self._file.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, self._file)
        except OSError:
            # 写失败时清理临时文件，让上层异常继续抛
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ── 首启 ────────────────────────────────────────────────────────

    def bootstrap(self) -> Session:
        """若没有任何 session，自动建 session-1 并设为 current。返回 current session。"""
        if not self._sessions:
            sess = Session(id="session-1")
            self._sessions.append(sess)
            self._current_id = sess.id
            self._save()
        elif self._current_id is None:
            self._current_id = self._sessions[0].id
            self._save()
        return self.get_current()  # type: ignore[return-value]

    # ── 查询 ────────────────────────────────────────────────────────

    def list(self) -> list[Session]:
        """返回所有 session 副本（按 created_at 升序）。"""
        return list(self._sessions)

    def get(self, session_id: str) -> Optional[Session]:
        for s in self._sessions:
            if s.id == session_id:
                return s
        return None

    def get_current(self) -> Optional[Session]:
        if self._current_id is None:
            return None
        return self.get(self._current_id)

    @property
    def current_id(self) -> Optional[str]:
        return self._current_id

    # ── 变更 ────────────────────────────────────────────────────────

    def new(self, title: str = "") -> Session:
        """新建空 session 并切换为 current。"""
        ids = {s.id for s in self._sessions}
        sess = Session(id=_next_session_id(ids), title=title)
        self._sessions.append(sess)
        self._current_id = sess.id
        self._save()
        return sess

    def switch(self, session_id: str) -> Session:
        """切换 current session。session_id 不存在则抛 KeyError。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在")
        self._current_id = target.id
        target.last_active_at = _now_iso()
        self._save()
        return target

    async def delete(self, session_id: str, leader_store: Optional["LeaderStore"] = None) -> Session:
        """删除 session：联动清 checkpoint，若删的是 current 自动切到剩余首个或新建 session-1。

        async：因为 LeaderStore.purge 是异步的（AsyncSqliteSaver.adelete_thread）。

        Returns:
            被删除的 Session 实例。
        """
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在")

        # 先清 checkpoint —— 若清失败抛异常，sessions.json 保持原样
        if leader_store is not None:
            await leader_store.purge(session_id)

        self._sessions = [s for s in self._sessions if s.id != session_id]

        # current 联动：如果删的就是 current
        if self._current_id == session_id:
            if self._sessions:
                self._current_id = self._sessions[0].id
            else:
                # 没了 —— 自动建 session-1
                new_sess = Session(id="session-1")
                self._sessions.append(new_sess)
                self._current_id = new_sess.id

        self._save()
        return target

    def rename(self, session_id: str, new_title: str) -> Session:
        """改标题（用户主动 /title，强制覆盖）。"""
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在")
        target.title = new_title.strip()
        self._save()
        return target

    def set_title_if_empty(self, session_id: str, user_input: str) -> Session:
        """自动取标题：仅当 title 为空时基于 user_input 前 20 字生成。

        规则：
          - strip 后取前 20 个 Unicode 字符
          - 原文超过 20 字符则末尾追加 …

        非空时不动；同时刷新 last_active_at。
        """
        target = self.get(session_id)
        if target is None:
            raise KeyError(f"session '{session_id}' 不存在")

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
            raise KeyError(f"session '{session_id}' 不存在")
        target.last_active_at = _now_iso()
        self._save()
        return target

    # ── 调试 ────────────────────────────────────────────────────────

    @property
    def file_path(self) -> Path:
        return self._file
