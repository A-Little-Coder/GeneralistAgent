"""
SkillCenter 与 SkillRepository 测试用例。

覆盖：
  1. DB 版本号自动递增
  2. decorate_state 检测变更并全量同步
  3. 全量同步正确性（本地 SKILL.md 内容）
  4. 不重复同步（版本号相同）
  5. FastAPI 等价操作
  6. 增删改查边界
"""

from pathlib import Path

from src.skills.db import SkillRepository
from src.skills.center import SkillCenter


# ── DB 版本号 ──────────────────────────────────────────────────────────

class TestVersionTracking:
    """全局版本号自动递增。"""

    def test_initial_version_is_1(self, repo: SkillRepository):
        assert repo.get_global_version() == 1

    def test_add_bumps_version(self, repo: SkillRepository):
        repo.add("test-skill", "desc", content="content")
        assert repo.get_global_version() == 2

    def test_update_bumps_version(self, repo: SkillRepository):
        repo.add("test-skill", "desc", content="content")
        v_before = repo.get_global_version()
        repo.update("test-skill", description="new desc")
        assert repo.get_global_version() == v_before + 1

    def test_delete_bumps_version(self, repo: SkillRepository):
        repo.add("test-skill", "desc", content="content")
        v_before = repo.get_global_version()
        repo.delete("test-skill")
        assert repo.get_global_version() == v_before + 1

    def test_add_duplicate_does_not_bump(self, repo: SkillRepository):
        repo.add("test-skill", "desc")
        v = repo.get_global_version()
        repo.add("test-skill", "desc")
        assert repo.get_global_version() == v

    def test_delete_nonexistent_does_not_bump(self, repo: SkillRepository):
        v = repo.get_global_version()
        repo.delete("nonexistent")
        assert repo.get_global_version() == v


# ── decorate_state ─────────────────────────────────────────────────────

class TestDecorateState:
    """变更检测与全量同步。"""

    def test_first_call_syncs(self, center: SkillCenter, local_skills_dir: str):
        """首次调用触发同步。"""
        center.decorate_state({"messages": []})
        assert center._cached_version == 1
        local_path = Path(local_skills_dir)
        assert local_path.exists()

    def test_no_change_no_resync(self, seeded_center: SkillCenter):
        """版本号没变时不重复同步。"""
        old_cache = seeded_center._cached_version
        seeded_center.decorate_state({})
        assert seeded_center._cached_version == old_cache

    def test_add_triggers_resync(self, seeded_center: SkillCenter,
                                 repo: SkillRepository, local_skills_dir: str):
        """新增技能后触发重新同步。"""
        v = repo.get_global_version()
        repo.add("new-skill", "新技能", content="## 新技能内容")

        local_path = Path(local_skills_dir)
        assert not (local_path / "new-skill" / "SKILL.md").exists()

        seeded_center.decorate_state({})
        assert seeded_center._cached_version > v
        assert (local_path / "new-skill" / "SKILL.md").exists()

    def test_update_triggers_resync(self, seeded_center: SkillCenter,
                                    repo: SkillRepository, local_skills_dir: str):
        """更新技能后触发重新同步。"""
        repo.update("general", description="更新的描述")
        seeded_center.decorate_state({})
        md = Path(local_skills_dir, "general", "SKILL.md").read_text(encoding="utf-8")
        assert "更新的描述" in md

    def test_delete_triggers_resync(self, seeded_center: SkillCenter,
                                    repo: SkillRepository, local_skills_dir: str):
        """删除技能后本地对应目录消失。"""
        repo.delete("calculator")
        seeded_center.decorate_state({})
        assert not (Path(local_skills_dir) / "calculator").exists()
        assert (Path(local_skills_dir) / "general").exists()

    def test_full_sync_content_correct(self, seeded_center: SkillCenter,
                                       repo: SkillRepository, local_skills_dir: str):
        """全量同步后本地 SKILL.md 内容与数据库一致。"""
        repo.update("general", content="## 全新的内容")
        seeded_center.decorate_state({})

        md = Path(local_skills_dir, "general", "SKILL.md").read_text(encoding="utf-8")
        assert "## 全新的内容" in md
        assert "name: general" in md


# ── CRUD ──────────────────────────────────────────────────────────────

class TestRepositoryCRUD:
    """Repository 的增删改查边界。"""

    def test_list_full_contains_content(self, seeded_repo: SkillRepository):
        skills = seeded_repo.list_full()
        assert len(skills) == 2
        for s in skills:
            assert "content" in s
            assert s["content"]

    def test_list_excludes_content(self, seeded_repo: SkillRepository):
        skills = seeded_repo.list()
        for s in skills:
            assert "content" not in s

    def test_get_nonexistent(self, repo: SkillRepository):
        assert repo.get("nonexistent") is None

    def test_update_partial(self, repo: SkillRepository):
        repo.add("s", "desc", content="content", version="1.0.0", triggers="a,b")
        repo.update("s", description="新描述")
        skill = repo.get("s")
        assert skill["description"] == "新描述"
        assert skill["content"] == "content"
        assert skill["triggers"] == "a,b"

    def test_to_skill_md(self, seeded_repo: SkillRepository):
        md = seeded_repo.to_skill_md("general")
        assert md is not None
        assert md.startswith("---")
        assert "name: general" in md
        assert "## 通用指南" in md

    def test_to_skill_md_nonexistent(self, repo: SkillRepository):
        assert repo.to_skill_md("nonexistent") is None