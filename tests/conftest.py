"""
测试共享配置 — 提供隔离的测试数据库和 SkillCenter 实例。
"""

from pathlib import Path

import pytest

from src.skills.db import SkillRepository
from src.skills.center import SkillCenter


@pytest.fixture
def test_dir(tmp_path: Path) -> Path:
    """临时测试目录。"""
    return tmp_path


@pytest.fixture
def remote_db_dir(test_dir: Path) -> str:
    """隔离的远程数据库目录。"""
    d = test_dir / "remote" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@pytest.fixture
def local_skills_dir(test_dir: Path) -> str:
    """隔离的本地技能目录。"""
    d = test_dir / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@pytest.fixture
def repo(remote_db_dir: str) -> SkillRepository:
    """隔离的 SkillRepository 实例。"""
    return SkillRepository(db_dir=remote_db_dir)


@pytest.fixture
def center(remote_db_dir: str, local_skills_dir: str) -> SkillCenter:
    """隔离的 SkillCenter 实例（空数据库）。"""
    return SkillCenter(remote_db_dir=remote_db_dir, local_skills_dir=local_skills_dir)


@pytest.fixture
def seeded_repo(repo: SkillRepository) -> SkillRepository:
    """预置两条技能的 SkillRepository。"""
    repo.add("general", "通用技能", content="## 通用指南\n通用内容", triggers="通用")
    repo.add("calculator", "精确计算器", content="## 计算\n计算内容", triggers="计算")
    return repo


@pytest.fixture
def seeded_center(remote_db_dir: str, local_skills_dir: str,
                  seeded_repo: SkillRepository) -> SkillCenter:
    """预置两条技能的 SkillCenter。"""
    center = SkillCenter(remote_db_dir=remote_db_dir, local_skills_dir=local_skills_dir)
    center.decorate_state({})  # 触发首次同步
    return center