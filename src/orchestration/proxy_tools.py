"""
代理 Teammate 访问外部 Agent 服务的工具工厂。

设计要点（见 openspec/changes/add-agent-team-orchestration/design.md D5）：
  - 这些工具**仅装配给代理 Teammate**，Leader 工具集中不出现
  - 支持两种访问方式：
      * `http` —— 非标准化的 HTTP 网络请求（用 httpx.AsyncClient）
      * `mcp`  —— 通过 MCP server 工具调用（占位实现，留扩展点）
  - 统一在工具层做超时与一次重试（5xx / 网络错误）

接口约定（ProxyServiceConfig）：
  name        : 服务名（同 SKILL 名后缀，如 chatbi）
  access_kind : "http" | "mcp"
  base_url    : HTTP 模式下的服务地址
  auth_header : HTTP 模式下的 Authorization header（可空）
  timeout     : 秒，默认 30
  mcp_command : MCP 模式下启动 MCP server 的命令（占位）

返回的工具名形如 `<service>_query`（HTTP）或 `<service>_<mcp_tool>`（MCP）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.interface import log
from src.persistence.tool_truncate import truncate_for_persist


# ── 配置数据类 ─────────────────────────────────────────────────────────


@dataclass
class ProxyServiceConfig:
    """单个外部 Agent 服务的访问配置。

    由 Config.load_proxy_services() 从 .env 中按 `PROXY_<NAME>_*` 前缀解析。
    """
    name: str                       # 服务名（小写，如 "chatbi"）
    access_kind: str                # "http" | "mcp"
    base_url: str = ""              # http 模式
    auth_header: str = ""           # http 模式（如 "Bearer xxx"）
    timeout: int = 30
    mcp_command: str = ""           # mcp 模式（占位，未来扩展）
    skill_name: str = ""            # 关联的 SKILL 名（默认 proxy_<name>）

    def resolved_skill_name(self) -> str:
        return self.skill_name or f"proxy-{self.name}"


# ── 工具入参 schema ────────────────────────────────────────────────────


class _QueryArgs(BaseModel):
    """HTTP 代理工具的统一入参 schema。"""
    question: str = Field(..., description="自然语言问数描述")
    timeout: Optional[int] = Field(None, description="超时秒数，默认走配置")


# ── 工具构造 ──────────────────────────────────────────────────────────


def build_proxy_tools(svc: ProxyServiceConfig) -> list[BaseTool]:
    """根据服务配置构造一组访问工具。

    HTTP 模式：暴露一个 `<svc.name>_query` 工具，POST 到 `{base_url}/query`，
    body 形如 `{"question": "..."}`，期望返回 JSON。

    NL2SQL_SSE 模式：专属 NL2SQL Agent 服务接入 —— POST 到 `/api/v1/query`
    并消费 SSE 流，附带 databases / tables 辅助工具。

    MCP 模式：当前为占位实现 —— 抛 NotImplementedError；待真实 MCP 客户端
    接入后补全。这样 Leader 流程能先以 HTTP 跑通，不阻塞架构。
    """
    if svc.access_kind == "http":
        return [_build_http_query_tool(svc)]
    if svc.access_kind == "nl2sql_sse":
        # 延迟 import 避免循环（nl2sql_tools 引用 ProxyServiceConfig）
        from src.orchestration.nl2sql_tools import build_nl2sql_tools
        return build_nl2sql_tools(svc)
    if svc.access_kind == "mcp":
        return _build_mcp_tools(svc)
    raise ValueError(f"未支持的 access_kind: {svc.access_kind!r}")


def _build_http_query_tool(svc: ProxyServiceConfig) -> BaseTool:
    """HTTP 模式：POST {base_url}/query。"""

    tool_name = f"{svc.name}_query"
    description = (
        f"调用外部 {svc.name} 服务（HTTP），把自然语言问题转为查询结果。"
        f"参数 question 必填。失败会自动对 5xx/网络错误重试一次。"
    )

    async def _call(question: str, timeout: Optional[int] = None) -> dict:
        """统一发起 HTTP POST + 一次重试。"""
        url = svc.base_url.rstrip("/") + "/query"
        headers = {}
        if svc.auth_header:
            headers["Authorization"] = svc.auth_header
        timeout_s = timeout or svc.timeout
        # 连接 / 写超时单独短设；read 用 timeout_s
        client_timeout = httpx.Timeout(
            connect=10.0,
            read=float(timeout_s),
            write=10.0,
            pool=10.0,
        )

        log.proxy_log(f"🡒 POST {url} question={log.truncate(question, 80)}")

        last_exc: Optional[Exception] = None
        for attempt in range(2):  # 最多 1 次重试
            try:
                async with httpx.AsyncClient(timeout=client_timeout) as client:
                    resp = await client.post(url, json={"question": question}, headers=headers)
                    # 5xx → 重试；4xx → 直接返回错误结构
                    if 500 <= resp.status_code < 600 and attempt == 0:
                        log.proxy_log(f"✗ HTTP {resp.status_code} (5xx) → 1s 后重试")
                        await asyncio.sleep(1.0)
                        continue
                    if resp.status_code >= 400:
                        log.proxy_log(
                            f"✗ HTTP {resp.status_code}: {log.truncate(_safe_text(resp), 200)}"
                        )
                        return {
                            "status": "error",
                            "http_status": resp.status_code,
                            "body": truncate_for_persist(_safe_text(resp)),
                        }
                    log.proxy_log(f"🡐 ✓ HTTP {resp.status_code}")
                    return _try_json(resp)
            except httpx.ConnectError as e:
                last_exc = e
                log.proxy_log(f"✗ ConnectError: {e}（服务似乎未启动 / 端口错）")
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                break
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                log.proxy_log(f"✗ {type(e).__name__}: {e}")
                if attempt == 0:
                    await asyncio.sleep(1.0)
                    continue
                break
        return {"status": "error", "reason": f"{type(last_exc).__name__}: {last_exc}"}

    return StructuredTool.from_function(
        coroutine=_call,
        name=tool_name,
        description=description,
        args_schema=_QueryArgs,
    )


def _build_mcp_tools(svc: ProxyServiceConfig) -> list[BaseTool]:
    """MCP 模式占位实现 —— 等真实 MCP 客户端接入后补全。

    返回一个抛 NotImplementedError 的桩工具，让架构层先跑通。
    """
    tool_name = f"{svc.name}_mcp_query"

    async def _call(question: str, timeout: Optional[int] = None) -> dict:
        raise NotImplementedError(
            f"MCP 访问工具尚未实现（service={svc.name}）。"
            f"当前 mcp_command={svc.mcp_command!r}"
        )

    return [StructuredTool.from_function(
        coroutine=_call,
        name=tool_name,
        description=f"[占位] 通过 MCP 访问 {svc.name} —— 当前尚未实现",
        args_schema=_QueryArgs,
    )]


# ── 辅助 ──────────────────────────────────────────────────────────────


def _try_json(resp: httpx.Response) -> dict:
    """尝试 JSON 解析；失败则降级为文本包装。"""
    try:
        return resp.json()
    except Exception:
        return {"status": "ok", "raw_text": _safe_text(resp)}


def _safe_text(resp: httpx.Response) -> str:
    """避免 GBK 等编码异常 —— 用 utf-8 + replace 兜底。"""
    try:
        return resp.text
    except Exception:
        return resp.content.decode("utf-8", errors="replace")
