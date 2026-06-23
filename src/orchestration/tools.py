"""
编排工具 — 把团队 / 任务 / 消息 / 代理 Teammate 拉起 等能力包装为 LangChain Tool。

设计要点（见 design.md D5）：
  - 这些工具仅由 Leader 调用，注入到 build_agent(tools=...)
  - Leader 调 spawn_teammate 时**只能引用 proxy_service 名**（如 "chatbi"），
    不直接接触 base_url / auth_header —— 这些由 TeamManager + Config 内部装配
  - 工具返回值统一是 JSON 友好的 dict / str，避免把 Teammate / Runner 实例
    透出到模型上下文

模块组织：
  - build_orchestration_tools(ctx) 返回一组 BaseTool；ctx 持有
    TeamManager / Config / Leader 模型 等运行时句柄
  - 每个工具都是 StructuredTool 的薄包装，逻辑放在 ctx 上以便单测
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.core.config import Config
from src.interface import log
from src.orchestration.proxy_tools import ProxyServiceConfig
from src.orchestration.team import Team, TeamManager
from src.orchestration.teammate import (
    Teammate,
    create_proxy_teammate,
    create_teammate,
)


# ── ctx：所有编排工具共享的运行时句柄 ────────────────────────────────


@dataclass
class OrchestrationContext:
    """编排工具运行时上下文 —— 一次 build_orchestration_tools 共享。

    持有：
      - team_manager : 团队注册中心（创建 / 删除 / 查询团队）
      - config       : 全局配置（找代理服务、找 skills 根目录）
      - leader_model : Leader 的 LLM 实例；Teammate 默认 fallback 模型
      - default_team : Leader 默认操作的团队名（避免每次都得传 team_name）
    """
    team_manager: TeamManager
    config: Config
    leader_model: BaseChatModel
    default_team: str = "main"

    def get_team(self, team_name: Optional[str]) -> Team:
        """按名取团队；未传时使用 default_team。"""
        name = team_name or self.default_team
        team = self.team_manager.get(name)
        if team is None:
            raise KeyError(f"团队 '{name}' 不存在；请先 team_create")
        return team


# ── 工具入参 schema ───────────────────────────────────────────────────


class _TeamCreateArgs(BaseModel):
    team_name: str = Field(..., description="新建团队名")
    leader_name: str = Field("leader", description="Leader 标识，默认 'leader'")


class _TeamDeleteArgs(BaseModel):
    team_name: str = Field(..., description="要删除的团队名")
    force: bool = Field(False, description="是否强制关闭活跃 Teammate")


class _SpawnTeammateArgs(BaseModel):
    name: str = Field(..., description="Teammate 名（团队内唯一）")
    proxy_service: Optional[str] = Field(
        None,
        description="代理外部服务名（如 'chatbi'）。"
                    "传入则自动装配该服务的访问工具与 SKILL 限定；"
                    "为空则创建普通 Teammate（无外部访问工具）。",
    )
    team_name: Optional[str] = Field(None, description="目标团队；为空使用默认团队")
    role_prompt: str = Field("", description="额外角色 prompt（可空）")


class _SendMessageArgs(BaseModel):
    to: str = Field(..., description="收件人 Teammate 名（或 '*' 广播）")
    content: str = Field(..., description="消息内容")
    team_name: Optional[str] = Field(None, description="目标团队；为空使用默认团队")


class _AssignTaskArgs(BaseModel):
    teammate_name: str = Field(..., description="任务指派的 Teammate 名")
    description: str = Field(..., description="任务描述（Teammate 将以此为 prompt）")
    team_name: Optional[str] = Field(None, description="目标团队；为空使用默认团队")


class _TaskListArgs(BaseModel):
    team_name: Optional[str] = Field(None, description="目标团队；为空使用默认团队")


class _WaitForMessageArgs(BaseModel):
    timeout: float = Field(
        180.0,
        description="等待超时秒数。建议 30~300。超时后返回 status='timeout'，Leader 可选择继续等或查 task_list_query",
    )
    team_name: Optional[str] = Field(None, description="目标团队；为空使用默认团队")


# ── 工具工厂 ──────────────────────────────────────────────────────────


def build_orchestration_tools(ctx: OrchestrationContext) -> list[BaseTool]:
    """构建一组编排工具。每次 build_agent 调一次。"""
    return [
        _tool_team_create(ctx),
        _tool_team_delete(ctx),
        _tool_team_list(ctx),
        _tool_spawn_teammate(ctx),
        _tool_send_message(ctx),
        _tool_assign_task(ctx),
        _tool_task_list_query(ctx),
        _tool_wait_for_message(ctx),
    ]


# ── 单个工具实现 ─────────────────────────────────────────────────────


def _tool_team_create(ctx: OrchestrationContext) -> BaseTool:
    def _run(team_name: str, leader_name: str = "leader") -> dict:
        log.indent_log(f"team_create(name={team_name}, leader={leader_name})")
        try:
            team = ctx.team_manager.create_team(name=team_name, leader_name=leader_name)
            return {"status": "ok", "team": team.name, "leader": team.leader_name}
        except (ValueError, PermissionError) as e:
            log.indent_log(f"team_create ✗ {e}")
            return {"status": "error", "reason": str(e)}

    return StructuredTool.from_function(
        func=_run,
        name="team_create",
        description="创建一个新团队，返回团队名与 leader 名。已存在则报错。",
        args_schema=_TeamCreateArgs,
    )


def _tool_team_delete(ctx: OrchestrationContext) -> BaseTool:
    async def _run(team_name: str, force: bool = False) -> dict:
        try:
            await ctx.team_manager.delete_team(team_name, force=force)
            return {"status": "ok", "deleted": team_name}
        except (KeyError, RuntimeError) as e:
            return {"status": "error", "reason": str(e)}

    return StructuredTool.from_function(
        coroutine=_run,
        name="team_delete",
        description="删除团队。force=True 时会先 shutdown 所有活跃 Teammate。",
        args_schema=_TeamDeleteArgs,
    )


def _tool_team_list(ctx: OrchestrationContext) -> BaseTool:
    def _run() -> dict:
        names = ctx.team_manager.list_teams()
        out = []
        for n in names:
            team = ctx.team_manager.get(n)
            out.append({
                "name": n,
                "leader": team.leader_name if team else "",
                "members": list(team.members.keys()) if team else [],
            })
        return {"status": "ok", "teams": out}

    return StructuredTool.from_function(
        func=_run,
        name="team_list",
        description="列出所有团队及其成员。",
    )


def _tool_spawn_teammate(ctx: OrchestrationContext) -> BaseTool:
    """关键工具：拉起 Teammate。

    - proxy_service 非空：调 create_proxy_teammate，由 ctx 从 Config 找服务配置
      （Leader 看不到 base_url / token）
    - proxy_service 为空：调 create_teammate，普通 Teammate（不装配外部工具）
    """

    async def _run(
        name: str,
        proxy_service: Optional[str] = None,
        team_name: Optional[str] = None,
        role_prompt: str = "",
    ) -> dict:
        log.indent_log(
            f"spawn_teammate(name={name}, proxy_service={proxy_service or '-'}, team={team_name or 'default'})"
        )
        try:
            team = ctx.get_team(team_name)
        except KeyError as e:
            log.indent_log(f"spawn_teammate ✗ {e}")
            return {"status": "error", "reason": str(e)}

        if proxy_service:
            svc: Optional[ProxyServiceConfig] = ctx.config.get_proxy_service(proxy_service)
            if svc is None:
                log.indent_log(f"spawn_teammate ✗ unknown proxy_service '{proxy_service}'")
                return {
                    "status": "error",
                    "reason": f"未找到代理服务 '{proxy_service}'；请在 .env 中配置 PROXY_*",
                }
            teammate = create_proxy_teammate(
                name=name,
                team_name=team.name,
                service=svc,
                skills_root=ctx.config.skills_dir,
                fallback_model=ctx.leader_model,
                extra_system_prompt=role_prompt,
            )
        else:
            teammate = create_teammate(
                name=name,
                team_name=team.name,
                fallback_model=ctx.leader_model,
                skills_dir=ctx.config.skills_dir,
                extra_system_prompt=role_prompt,
            )

        try:
            ctx.team_manager.spawn_teammate(team.name, teammate)
        except (KeyError, ValueError, PermissionError) as e:
            log.indent_log(f"spawn_teammate ✗ {e}")
            return {"status": "error", "reason": str(e)}

        log.indent_log(
            f"spawn_teammate ✓ {teammate.name} tools=[{', '.join(t.name for t in teammate.tools)}]"
        )
        return {
            "status": "ok",
            "teammate": teammate.name,
            "team": team.name,
            "tools": [t.name for t in teammate.tools],
            "proxy_service": proxy_service or None,
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="spawn_teammate",
        description=(
            "拉起一个 Teammate 加入指定团队。"
            "若需要访问外部 Agent 服务，传 proxy_service 名（如 'chatbi'），"
            "工具会自动装配访问工具与 SKILL；否则创建普通 Teammate。"
            "Teammate 启动后会进入 idle 循环，可通过 assign_task 或 send_message 调用。"
        ),
        args_schema=_SpawnTeammateArgs,
    )


def _tool_send_message(ctx: OrchestrationContext) -> BaseTool:
    async def _run(to: str, content: str, team_name: Optional[str] = None) -> dict:
        log.indent_log(f"send_message(to={to}, team={team_name or 'default'})")
        try:
            team = ctx.get_team(team_name)
        except KeyError as e:
            log.indent_log(f"send_message ✗ {e}")
            return {"status": "error", "reason": str(e)}

        from src.orchestration.mailbox import Message
        delivered = await team.mailbox.send(Message(
            sender=team.leader_name,
            to=to,
            content=content,
            kind="message",
        ))
        log.indent_log(f"send_message ✓ delivered={delivered}")
        return {"status": "ok", "delivered_count": delivered, "to": to}

    return StructuredTool.from_function(
        coroutine=_run,
        name="send_message",
        description="给团队某个 Teammate 发消息（to='*' 广播）。该消息会唤醒 Teammate 处理。",
        args_schema=_SendMessageArgs,
    )


def _tool_assign_task(ctx: OrchestrationContext) -> BaseTool:
    def _run(teammate_name: str, description: str, team_name: Optional[str] = None) -> dict:
        log.indent_log(
            f"assign_task(to={teammate_name}, team={team_name or 'default'}, desc={log.truncate(description, 80)})"
        )
        try:
            team = ctx.get_team(team_name)
        except KeyError as e:
            log.indent_log(f"assign_task ✗ {e}")
            return {"status": "error", "reason": str(e)}

        # 创建任务并直接指派
        task = team.task_list.create(description=description, assignee=teammate_name)
        log.indent_log(f"assign_task ✓ task_id={task.id}")
        return {
            "status": "ok",
            "task_id": task.id,
            "assigned_to": teammate_name,
            "team": team.name,
        }

    return StructuredTool.from_function(
        func=_run,
        name="assign_task",
        description=(
            "在共享 Task List 中创建一条任务并指派给某 Teammate。"
            "Teammate 的 Runner 会在 idle 循环中自动领取并执行。"
            "Leader 可通过 task_list_query 查询完成状态。"
        ),
        args_schema=_AssignTaskArgs,
    )


def _tool_task_list_query(ctx: OrchestrationContext) -> BaseTool:
    def _run(team_name: Optional[str] = None) -> dict:
        try:
            team = ctx.get_team(team_name)
        except KeyError as e:
            return {"status": "error", "reason": str(e)}

        all_tasks = team.task_list.list_all()
        return {
            "status": "ok",
            "team": team.name,
            "tasks": [
                {
                    "id": t.id,
                    "status": t.status,
                    "assignee": t.assignee,
                    "description": t.description,
                    "result": t.result,
                }
                for t in all_tasks
            ],
        }

    return StructuredTool.from_function(
        func=_run,
        name="task_list_query",
        description="查询指定团队的全部任务状态。",
        args_schema=_TaskListArgs,
    )


def _tool_wait_for_message(ctx: OrchestrationContext) -> BaseTool:
    """Leader 阻塞等待 Teammate 通过 Mailbox 投递的回信。

    替代 Leader 反复轮询 task_list_query 的忙等模式（D9）。
    Runner 在任务完成 / 失败 / 消息回复时会自动投递通知，本工具阻塞挂起
    Leader 信箱直到有消息或超过 timeout。等待期间不消耗 LLM 推理。
    """

    async def _run(timeout: float = 180.0, team_name: Optional[str] = None) -> dict:
        try:
            team = ctx.get_team(team_name)
        except KeyError as e:
            return {"status": "error", "reason": str(e)}

        leader = team.leader_name
        log.indent_log(f"wait_for_message(team={team.name}, leader={leader}, timeout={timeout}s) …")
        try:
            msg = await asyncio.wait_for(team.mailbox.recv(leader), timeout=timeout)
        except asyncio.TimeoutError:
            log.indent_log(f"wait_for_message ⏱ 超时（{timeout}s）")
            return {"status": "timeout", "team": team.name}

        log.indent_log(
            f"wait_for_message ✓ from={msg.sender} kind={msg.kind} meta={log.fmt_kv(msg.meta or {})}"
        )
        return {
            "status": "ok",
            "from": msg.sender,
            "kind": msg.kind,
            "content": msg.content,
            "meta": msg.meta or {},
            "team": team.name,
        }

    return StructuredTool.from_function(
        coroutine=_run,
        name="wait_for_message",
        description=(
            "阻塞等待团队成员（Teammate）发来的消息，常用场景：分配任务后等结果回来。"
            "Teammate 完成任务会自动通过 Mailbox 通知 Leader，kind 取 "
            "'task_completed' / 'task_failed' / 'message_reply' 等。"
            "meta 字段包含 task_id / teammate_name 等元数据。"
            "超时返回 status='timeout'，可继续调用本工具继续等待或者用 task_list_query 兜底。"
            "**这是推荐的等待方式，不要用 task_list_query 反复轮询！**"
        ),
        args_schema=_WaitForMessageArgs,
    )
