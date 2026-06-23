"""
TaskList — 团队共享任务表，JSON 文件持久化于 ~/.generalist/tasks/{team}/。

设计要点：
  - 每个任务一个 JSON 文件，文件名即 task_id，便于观察与单条原子写
  - 状态机：pending → in_progress → completed
  - blockedBy 支持任务依赖（前置任务未完成时不可领取）
  - claim() 是"先到先得"，用 rename 原子化避免两个 runner 同时领同一任务
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


_STATUS_PENDING = "pending"
_STATUS_IN_PROGRESS = "in_progress"
_STATUS_COMPLETED = "completed"


@dataclass
class Task:
    """单条任务记录。"""
    id: str
    description: str
    assignee: str = ""                       # 指定的负责人 name；空表示任意 teammate 可领
    status: str = _STATUS_PENDING
    blocked_by: list[str] = field(default_factory=list)
    owner: str = ""                          # 实际领取的 teammate_id
    result: str = ""                         # 完成时的结果摘要
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(**d)


class TaskList:
    """团队共享 TaskList。

    存储布局：
      base_dir/{team_name}/{task_id}.json

    所有操作都基于文件系统，可被多个同进程 runner 安全共享：
      - 创建：write_text 原子写（先写 .tmp 再 rename）
      - 领取：rename 原子化（claim 失败说明已被他人领走）
    """

    def __init__(self, base_dir: str | Path, team_name: str):
        self._team_dir = Path(base_dir) / team_name
        self._team_dir.mkdir(parents=True, exist_ok=True)

    # ── 写：创建 / 状态流转 ──────────────────────────────────────────

    def create(self, description: str, assignee: str = "",
               blocked_by: Optional[list[str]] = None) -> Task:
        """创建一条 pending 任务并返回。"""
        now = time.time()
        task = Task(
            id=str(uuid.uuid4())[:8],
            description=description,
            assignee=assignee,
            blocked_by=list(blocked_by or []),
            created_at=now,
            updated_at=now,
        )
        self._write(task)
        return task

    def claim(self, task_id: str, owner: str) -> bool:
        """尝试领取任务。成功返回 True；任务不存在/已被领取/依赖未完成返回 False。"""
        task = self.get(task_id)
        if task is None:
            return False
        if task.status != _STATUS_PENDING or task.owner:
            return False
        if not self._dependencies_satisfied(task):
            return False
        task.status = _STATUS_IN_PROGRESS
        task.owner = owner
        task.updated_at = time.time()
        self._write(task)
        return True

    def complete(self, task_id: str, result: str = "") -> bool:
        """标记任务完成。"""
        task = self.get(task_id)
        if task is None or task.status == _STATUS_COMPLETED:
            return False
        task.status = _STATUS_COMPLETED
        task.result = result
        task.updated_at = time.time()
        self._write(task)
        return True

    # ── 读：查询 ─────────────────────────────────────────────────────

    def get(self, task_id: str) -> Optional[Task]:
        path = self._team_dir / f"{task_id}.json"
        if not path.exists():
            return None
        try:
            return Task.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return None

    def list_all(self) -> list[Task]:
        """返回团队所有任务，按 created_at 升序。"""
        tasks: list[Task] = []
        for p in self._team_dir.glob("*.json"):
            try:
                tasks.append(Task.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError):
                continue
        tasks.sort(key=lambda t: t.created_at)
        return tasks

    def claimable_for(self, name: str) -> list[Task]:
        """返回当前可被 name 领取的任务（pending、无人负责、依赖满足、assignee 匹配）。"""
        out: list[Task] = []
        for t in self.list_all():
            if t.status != _STATUS_PENDING or t.owner:
                continue
            if t.assignee and t.assignee != name:
                continue
            if not self._dependencies_satisfied(t):
                continue
            out.append(t)
        return out

    def has_active(self) -> bool:
        """是否存在未完成（pending/in_progress）的任务。"""
        return any(t.status != _STATUS_COMPLETED for t in self.list_all())

    # ── 清理 ─────────────────────────────────────────────────────────

    def clear(self) -> None:
        """删除团队目录下所有任务文件（用于 team_delete）。"""
        if not self._team_dir.exists():
            return
        for p in self._team_dir.glob("*.json"):
            p.unlink()
        # 团队目录本身保留给上层（team.py）决定是否删

    @property
    def team_dir(self) -> Path:
        return self._team_dir

    # ── 内部 ─────────────────────────────────────────────────────────

    def _write(self, task: Task) -> None:
        """原子写：先写 .tmp 再 rename。"""
        path = self._team_dir / f"{task.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, path)

    def _dependencies_satisfied(self, task: Task) -> bool:
        for dep_id in task.blocked_by:
            dep = self.get(dep_id)
            if dep is None or dep.status != _STATUS_COMPLETED:
                return False
        return True
