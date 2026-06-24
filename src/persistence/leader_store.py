"""
LeaderStore —— 封装 LangGraph 官方 AsyncSqliteSaver，承担 Leader 跨进程对话历史持久化。

设计要点：
  - 单文件 SQLite（默认 `memory/leader.db`），不与 skills.db 共用
  - 使用 **AsyncSqliteSaver**：CLI 走 asyncio + agent.astream，必须用异步实现
    （同步的 SqliteSaver 调 astream 会抛 NotImplementedError）
  - 维持一个长 aiosqlite 连接，REPL 进程整生命周期复用
  - `purge(session_id)` 转发到 AsyncSqliteSaver.adelete_thread；删除 session 时一并清掉
  - 初始化分两步：同步构造 + `async setup()`，让 LeaderStore 在 asyncio 主循环内启动

与 Teammate 的关系：Teammate 完全 RAM 化（MemorySaver，同步），不经本模块。
Teammate 的 Runner 不在主事件循环以外的线程，仍可用同步 MemorySaver。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.persistence.user_migration import migrate_legacy_thread_ids


# 项目根/memory/ —— 与 skills/ teams/ 同级，独立目录
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MEMORY_DIR = _PROJECT_ROOT / "memory"
DEFAULT_DB_FILENAME = "leader.db"


class LeaderStore:
    """Leader 对话历史持久化存储（异步）。

    用法：
        store = LeaderStore()
        await store.setup()                 # 必须 await，在 asyncio 循环内
        saver = store.get_checkpointer()
        # ... build_agent(checkpointer=saver, ...)
        await store.purge("sess-001")       # /delete 时调用
        await store.aclose()                # 退出时调用

    便捷的同步入口：
        store = await LeaderStore.create()  # 一步搞定 init + setup
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
    ):
        if db_path is not None:
            self._db_path = Path(db_path)
            self._memory_dir = self._db_path.parent
        else:
            self._memory_dir = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
            self._db_path = self._memory_dir / DEFAULT_DB_FILENAME

        self._memory_dir.mkdir(parents=True, exist_ok=True)

        self._conn: Optional[aiosqlite.Connection] = None
        self._saver: Optional[AsyncSqliteSaver] = None
        self._is_setup = False

    @classmethod
    async def create(
        cls,
        db_path: Optional[Path] = None,
        memory_dir: Optional[Path] = None,
    ) -> "LeaderStore":
        """异步工厂：构造 + setup 一步完成。"""
        store = cls(db_path=db_path, memory_dir=memory_dir)
        await store.setup()
        return store

    async def setup(self) -> None:
        """打开 aiosqlite 连接 + 建表 + 一次性迁移旧 thread_id（幂等）。"""
        if self._is_setup:
            return
        self._conn = await aiosqlite.connect(str(self._db_path))
        self._saver = AsyncSqliteSaver(self._conn)
        await self._saver.setup()
        # 旧版（add-memory-persistence）的 thread_id 是裸 session_id，
        # 加入 user_id 维度后改为 "{user_id}:{session_id}" 格式；
        # 这里对历史数据做一次性幂等迁移：无冒号 → "default:<原值>"。
        try:
            affected = await migrate_legacy_thread_ids(self._conn)
            if affected:
                # 这里不引 log 模块以避免循环；调用方需要可观测的话由 CLI 启动日志兜底
                print(f"[LeaderStore] 迁移 {affected} 行旧 thread_id → default:<原值>")
        except Exception as e:
            # 迁移失败不阻塞 setup —— 用户后续仍可正常使用，仅旧数据可能不可见
            print(f"[LeaderStore] ⚠ 旧 thread_id 迁移失败：{type(e).__name__}: {e}")
        self._is_setup = True

    # ── 对外接口 ─────────────────────────────────────────────────────

    def get_checkpointer(self) -> BaseCheckpointSaver:
        """返回 LangGraph 兼容的 checkpointer，注入到 build_agent。"""
        if self._saver is None:
            raise RuntimeError("LeaderStore.setup() 未调用；请先 await store.setup()")
        return self._saver

    async def purge(self, session_id: str) -> None:
        """从底层数据库删除指定 thread_id 的所有 checkpoint。

        转发到 AsyncSqliteSaver.adelete_thread —— 它会同步清空 checkpoints / writes 两张表。
        若 thread_id 不存在不会报错（SQL DELETE 语义）。

        Args:
            session_id: LangGraph thread_id，对应 SessionManager 的 Session.id。
        """
        if self._saver is None:
            raise RuntimeError("LeaderStore.setup() 未调用")
        await self._saver.adelete_thread(session_id)

    async def list_thread_ids(self) -> list[str]:
        """列出库中所有 distinct thread_id —— 主要给测试/调试用。"""
        if self._conn is None:
            return []
        try:
            cur = await self._conn.execute(
                "SELECT DISTINCT thread_id FROM checkpoints"
            )
            rows = await cur.fetchall()
            await cur.close()
        except Exception:
            return []
        return [r[0] for r in rows]

    async def aclose(self) -> None:
        """关闭底层 aiosqlite 连接。重复 close 安全。"""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._saver = None
            self._is_setup = False

    # ── 同步包装（仅用于退出时兜底，主路径全部走 async） ──────────────

    def close_sync(self) -> None:
        """同步关闭 —— 仅供异常 finally 兜底使用。"""
        if self._conn is None:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 已在运行的 loop 里：调度 task 但不等待
                loop.create_task(self.aclose())
            else:
                loop.run_until_complete(self.aclose())
        except Exception:
            pass

    # ── 调试 ─────────────────────────────────────────────────────────

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def memory_dir(self) -> Path:
        return self._memory_dir

    def __repr__(self) -> str:
        return f"LeaderStore(db_path={self._db_path}, setup={self._is_setup})"
