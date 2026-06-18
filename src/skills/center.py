"""
Skill 管理中心 — Agent 侧的技能变更检测与本地同步。

职责：
  1. 通过 SkillRepository 连接 remote/skills/ 数据库，检测版本号变化
  2. 版本号变化时，全量从数据库拉取技能，写入本地 skills/{name}/SKILL.md
  3. 装饰 state 供 SkillsMiddleware 消费

使用方式：
    from src.skills.center import SkillCenter
    center = SkillCenter(remote_db_dir="./remote/skills", local_skills_dir="./skills")
    state = center.decorate_state(state)
"""

import shutil
from pathlib import Path
from typing import Any

from src.skills.db import SkillRepository


class SkillCenter:
    """技能管理中心 — 检测变更 + 同步到本地 skills/ 目录。

    Args:
        remote_db_dir: 远程数据库目录（remote/skills/）。
        local_skills_dir: 本地 skills/ 目录（Agent 读取用）。
    """

    def __init__(self, remote_db_dir: str, local_skills_dir: str):
        self._repo = SkillRepository(db_dir=remote_db_dir)
        self._local_dir = Path(local_skills_dir)
        self._local_dir.mkdir(parents=True, exist_ok=True)

        # 内存缓存：上次同步时的版本号
        self._cached_version: int = 0

    # ── 变更检测 ──────────────────────────────────────────────────────

    def decorate_state(self, state: dict) -> dict:
        """检测远程技能是否变更，必要时全量同步到本地。

        每次请求前调用：
          - 版本号未变 → 直接返回，零磁盘 IO
          - 版本号变了  → 全量从数据库拉取 → 写入本地 skills/ → 更新缓存版本号
        """
        current_version = self._repo.get_global_version()

        if current_version != self._cached_version:
            self._sync_all()
            self._cached_version = current_version

        return state

    def _sync_all(self) -> None:
        """全量同步：清空本地 skills/ → 从数据库拉取所有技能 → 写入磁盘。"""
        # 清空本地 skills/ 目录（保留目录本身）
        for item in self._local_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)

        # 从数据库拉取全部技能
        skills = self._repo.list_full()

        # 写入本地 skills/{name}/SKILL.md
        for skill in skills:
            skill_dir = self._local_dir / skill["name"]
            skill_dir.mkdir(parents=True, exist_ok=True)
            md = _skill_md_content(
                skill["name"], skill["description"],
                skill["version"], skill["triggers"], skill["content"],
            )
            (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")

    def get_skills_dir(self) -> str:
        """返回本地 skills 目录的 POSIX 路径（供 cli.py 传入 SkillsMiddleware）。"""
        return self._local_dir.as_posix()

    def get_latest_version(self) -> int:
        """查询远程数据库当前版本号（供外部查看）。"""
        return self._repo.get_global_version()


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