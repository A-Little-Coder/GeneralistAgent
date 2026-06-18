"""
Skill 管理服务 — FastAPI 接口，模拟用户远程管理技能。

用户通过此 API 对远程数据库中的技能进行增删改查。
不直接操作本地 skills/ 目录。

启动方式：
    uvicorn src.skills.server:app --reload --port 8000

API 端点：
    POST   /skills       — 添加技能
    GET    /skills       — 列出技能
    GET    /skills/{name}— 获取技能详情
    PUT    /skills/{name}— 更新技能
    DELETE /skills/{name}— 删除技能
    GET    /version      — 获取全局版本号
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.skills.db import SkillRepository

# ── 数据模型 ──────────────────────────────────────────────────────────

app = FastAPI(title="Skill 管理服务", version="1.0.0")

# 数据库目录：项目根目录下的 remote/skills/
_db_dir = Path(__file__).resolve().parent.parent.parent / "remote" / "skills"
_repo = SkillRepository(db_dir=str(_db_dir))


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    version: str = "1.0.0"
    triggers: str = ""


class SkillUpdate(BaseModel):
    description: str | None = None
    content: str | None = None
    version: str | None = None
    triggers: str | None = None


# ── API 端点 ─────────────────────────────────────────────────────────

@app.post("/skills")
def add_skill(skill: SkillCreate):
    """添加技能。"""
    ok = _repo.add(
        name=skill.name,
        description=skill.description,
        content=skill.content,
        version=skill.version,
        triggers=skill.triggers,
    )
    if not ok:
        raise HTTPException(status_code=409, detail=f"技能 '{skill.name}' 已存在")
    return {"message": f"技能 '{skill.name}' 已添加"}


@app.get("/skills")
def list_skills():
    """列出所有技能（摘要）。"""
    return _repo.list()


@app.get("/skills/{name}")
def get_skill(name: str):
    """获取单个技能详情。"""
    skill = _repo.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
    return skill


@app.put("/skills/{name}")
def update_skill(name: str, update: SkillUpdate):
    """更新技能。"""
    ok = _repo.update(
        name=name,
        description=update.description,
        content=update.content,
        version=update.version,
        triggers=update.triggers,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
    return {"message": f"技能 '{name}' 已更新"}


@app.delete("/skills/{name}")
def delete_skill(name: str):
    """删除技能。"""
    ok = _repo.delete(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"技能 '{name}' 不存在")
    return {"message": f"技能 '{name}' 已删除"}


@app.get("/version")
def get_version():
    """获取全局版本号。"""
    return {"global_version": _repo.get_global_version()}