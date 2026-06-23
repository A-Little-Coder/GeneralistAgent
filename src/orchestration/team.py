"""
Team — 多 Agent 协作的容器。

一个 Team 持有：
  - 共享 TaskList（基于文件目录）
  - 共享 Mailbox（基于 asyncio.Queue）
  - 成员名册：name -> Teammate / Runner
  - 绑定的 Leader 名称（仅 Leader 可 spawn_teammate / delete_team）

边界规则（与 Claude Code 一致，扁平名册）：
  - Teammate 不能 spawn_teammate（is_running_as_teammate() == True 时拒绝）
  - 删除 Team 时如有未结束的 Teammate，需先 shutdown
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.orchestration.context import is_running_as_teammate
from src.orchestration.mailbox import Mailbox
from src.orchestration.runner import Runner
from src.orchestration.task_list import TaskList
from src.orchestration.teammate import Teammate


# 默认的团队任务根目录：项目根/teams/ —— TaskList 不跨项目共用
# 由 src/core/config.py 的 Config.teams_root 提供给 TeamManager；这里仅作 fallback
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEAMS_ROOT = _PROJECT_ROOT / "teams"


@dataclass
class Team:
    """单个 Team 容器。"""
    name: str
    leader_name: str                                            # "leader" 或 Leader 自定义名
    teams_root: Path
    task_list: TaskList = field(init=False)
    mailbox: Mailbox = field(init=False)
    members: dict[str, tuple[Teammate, Runner]] = field(default_factory=dict, init=False)

    def __post_init__(self):
        self.task_list = TaskList(base_dir=self.teams_root, team_name=self.name)
        self.mailbox = Mailbox()
        # leader 也注册一个邮箱位用于接收 teammate 回信
        self.mailbox.register(self.leader_name)

    # ── 成员管理 ─────────────────────────────────────────────────────

    def add_teammate(self, teammate: Teammate) -> Runner:
        """把 Teammate 加入团队并启动 Runner。返回该 Runner。"""
        if teammate.name in self.members:
            raise ValueError(f"Teammate '{teammate.name}' 已在团队 '{self.name}'")
        runner = Runner(
            teammate=teammate,
            mailbox=self.mailbox,
            task_list=self.task_list,
            leader_name=self.leader_name,
        )
        runner.start()
        self.members[teammate.name] = (teammate, runner)
        return runner

    def has_active_members(self) -> bool:
        """是否存在未退出的 Teammate Runner。"""
        return any(
            r._task is not None and not r._task.done()
            for _, r in self.members.values()
        )

    async def shutdown_all(self) -> None:
        """向所有 Teammate 发 shutdown，等待全部退出。"""
        for name, (_, runner) in self.members.items():
            await runner.request_shutdown()
        for _, runner in self.members.values():
            await runner.wait_done()


class TeamManager:
    """所有 Team 的注册中心 + 生命周期管理。"""

    def __init__(self, teams_root: Optional[Path] = None):
        self._teams_root = Path(teams_root) if teams_root else DEFAULT_TEAMS_ROOT
        self._teams_root.mkdir(parents=True, exist_ok=True)
        self._teams: dict[str, Team] = {}

    # ── 创建 / 删除 ──────────────────────────────────────────────────

    def create_team(self, name: str, leader_name: str = "leader") -> Team:
        """创建团队容器。Teammate 不可创建团队（扁平名册规则）。"""
        if is_running_as_teammate():
            raise PermissionError("Teammates cannot create teams")
        if name in self._teams:
            raise ValueError(f"团队 '{name}' 已存在")
        team = Team(name=name, leader_name=leader_name, teams_root=self._teams_root)
        self._teams[name] = team
        return team

    def get(self, name: str) -> Optional[Team]:
        return self._teams.get(name)

    def list_teams(self) -> list[str]:
        return list(self._teams.keys())

    async def delete_team(self, name: str, force: bool = False) -> None:
        """删除团队。

        - 默认拒绝删除仍有活跃 Teammate 的团队
        - force=True 则先 shutdown_all 再清理
        """
        team = self._teams.get(name)
        if team is None:
            raise KeyError(f"团队 '{name}' 不存在")

        if team.has_active_members():
            if not force:
                raise RuntimeError(
                    f"团队 '{name}' 仍有活跃 Teammate，请先 shutdown 或使用 force=True"
                )
            await team.shutdown_all()

        # 清理共享 TaskList 文件 + 团队目录
        team.task_list.clear()
        team_dir = team.task_list.team_dir
        if team_dir.exists():
            shutil.rmtree(team_dir, ignore_errors=True)

        self._teams.pop(name, None)

    # ── 工具：spawn_teammate（Teammate 不可调用） ────────────────────

    def spawn_teammate(self, team_name: str, teammate: Teammate) -> Runner:
        """把 Teammate 加入指定团队。Teammate 不可 spawn 其他 Teammate。"""
        if is_running_as_teammate():
            raise PermissionError("Teammates cannot spawn other teammates")
        team = self._teams.get(team_name)
        if team is None:
            raise KeyError(f"团队 '{team_name}' 不存在")
        if teammate.team_name != team_name:
            raise ValueError(
                f"Teammate 的 team_name='{teammate.team_name}' 与目标团队 '{team_name}' 不一致"
            )
        return team.add_teammate(teammate)

    # ── 全局清理（进程退出钩子） ─────────────────────────────────────

    async def cleanup_all(self) -> None:
        """退出时清理所有团队 —— 异步关闭 Runner，删除 TaskList 文件。"""
        for name in list(self._teams.keys()):
            try:
                await self.delete_team(name, force=True)
            except (RuntimeError, KeyError):
                continue

    @property
    def teams_root(self) -> Path:
        return self._teams_root
