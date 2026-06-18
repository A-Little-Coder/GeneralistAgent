"""
Skill 数据库公共操作层 — 封装 SQLite 增删改查与版本号管理。

所有技能数据以 remote/skills/ 下的 SQLite 为唯一真相源。
skill_server.py 和 skill_center.py 都通过此模块操作数据库。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SKILLS_TABLE = """
CREATE TABLE IF NOT EXISTS skills (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    version     TEXT NOT NULL DEFAULT '1.0.0',
    content     TEXT NOT NULL DEFAULT '',
    triggers    TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL
);
"""

_META_TABLE = """
CREATE TABLE IF NOT EXISTS skill_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_INIT_VERSION = """
INSERT OR IGNORE INTO skill_meta (key, value) VALUES ('global_version', '1');
"""


def _skill_md_content(name: str, description: str, version: str,
                      triggers: str, content: str) -> str:
    """组装 SKILL.md 文件内容（YAML frontmatter + body）。"""
    parts = ["---"]
    parts.append(f'name: {name}')
    parts.append(f'description: {description}')
    if version:
        parts.append(f'version: {version}')
    if triggers:
        parts.append(f'triggers: {triggers}')
    parts.append("---")
    parts.append("")
    if content:
        parts.append(content)
    return "\n".join(parts)


class SkillRepository:
    """技能数据仓库 — 直接操作 SQLite 数据库。

    Args:
        db_dir: 数据库文件所在目录（如 remote/skills/）。
            该目录下包含 skills.db 和 skill_meta.db
    """

    def __init__(self, db_dir: str):
        self._db_dir = Path(db_dir)
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── 数据库初始化 ───────────────────────────────────────────────────

    def _init_db(self) -> None:
        """初始化两张数据库表。"""
        skills_conn = sqlite3.connect(str(self._db_dir / "skills.db"))
        meta_conn = sqlite3.connect(str(self._db_dir / "skill_meta.db"))
        try:
            skills_conn.execute(_SKILLS_TABLE)
            skills_conn.commit()
            meta_conn.execute(_META_TABLE)
            meta_conn.execute(_INIT_VERSION)
            meta_conn.commit()
        finally:
            skills_conn.close()
            meta_conn.close()

    def _skills_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_dir / "skills.db"))

    def _meta_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_dir / "skill_meta.db"))

    # ── 全局版本号 ────────────────────────────────────────────────────

    def get_global_version(self) -> int:
        """读取当前全局版本号。"""
        conn = self._meta_conn()
        try:
            row = conn.execute(
                "SELECT value FROM skill_meta WHERE key = 'global_version'"
            ).fetchone()
            return int(row[0]) if row else 1
        finally:
            conn.close()

    def bump_global_version(self) -> None:
        """全局版本号 +1。"""
        conn = self._meta_conn()
        try:
            conn.execute(
                "UPDATE skill_meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                "WHERE key = 'global_version'"
            )
            conn.commit()
        finally:
            conn.close()

    # ── CRUD ──────────────────────────────────────────────────────────

    def add(self, name: str, description: str = "", content: str = "",
            version: str = "1.0.0", triggers: str = "") -> bool:
        """添加技能。返回是否成功（False 表示已存在）。"""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._skills_conn()
        try:
            conn.execute(
                "INSERT INTO skills (name, description, version, content, triggers, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, description, version, content, triggers, now),
            )
            conn.commit()
            self.bump_global_version()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def update(self, name: str, description: str | None = None,
               content: str | None = None, version: str | None = None,
               triggers: str | None = None) -> bool:
        """更新技能，只更新提供的字段。返回是否找到。"""
        conn = self._skills_conn()
        try:
            row = conn.execute(
                "SELECT description, version, content, triggers FROM skills WHERE name = ?",
                (name,)
            ).fetchone()
            if not row:
                return False

            cur_desc, cur_ver, cur_content, cur_triggers = row
            new_desc = description if description is not None else cur_desc
            new_ver = version if version is not None else cur_ver
            new_content = content if content is not None else cur_content
            new_triggers = triggers if triggers is not None else cur_triggers
            now = datetime.now(timezone.utc).isoformat()

            conn.execute(
                "UPDATE skills SET description=?, version=?, content=?, triggers=?, updated_at=? WHERE name=?",
                (new_desc, new_ver, new_content, new_triggers, now, name),
            )
            conn.commit()
            self.bump_global_version()
            return True
        finally:
            conn.close()

    def delete(self, name: str) -> bool:
        """删除技能。返回是否找到。"""
        conn = self._skills_conn()
        try:
            cur = conn.execute("DELETE FROM skills WHERE name = ?", (name,))
            conn.commit()
            deleted = cur.rowcount > 0
            if deleted:
                self.bump_global_version()
            return deleted
        finally:
            conn.close()

    def list(self) -> list[dict[str, Any]]:
        """列出所有技能摘要（不含 content）。"""
        conn = self._skills_conn()
        try:
            rows = conn.execute(
                "SELECT name, description, version, triggers, updated_at FROM skills ORDER BY name"
            ).fetchall()
            return [
                dict(name=r[0], description=r[1], version=r[2],
                     triggers=r[3], updated_at=r[4])
                for r in rows
            ]
        finally:
            conn.close()

    def list_full(self) -> list[dict[str, Any]]:
        """列出所有技能的全部信息（含 content）。"""
        conn = self._skills_conn()
        try:
            rows = conn.execute(
                "SELECT name, description, version, content, triggers, updated_at FROM skills ORDER BY name"
            ).fetchall()
            return [
                dict(name=r[0], description=r[1], version=r[2],
                     content=r[3], triggers=r[4], updated_at=r[5])
                for r in rows
            ]
        finally:
            conn.close()

    def get(self, name: str) -> dict[str, Any] | None:
        """获取单个技能完整信息。"""
        conn = self._skills_conn()
        try:
            row = conn.execute(
                "SELECT name, description, version, content, triggers, updated_at FROM skills WHERE name = ?",
                (name,),
            ).fetchone()
            if not row:
                return None
            return dict(name=row[0], description=row[1], version=row[2],
                        content=row[3], triggers=row[4], updated_at=row[5])
        finally:
            conn.close()

    def to_skill_md(self, name: str) -> str | None:
        """生成 SKILL.md 文件内容。"""
        skill = self.get(name)
        if not skill:
            return None
        return _skill_md_content(
            skill["name"], skill["description"],
            skill["version"], skill["triggers"], skill["content"],
        )