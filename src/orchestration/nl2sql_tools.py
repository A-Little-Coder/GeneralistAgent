"""
NL2SQL 专属适配工具 —— 把外部 NL2SQL Agent 服务接入为代理 Teammate 的工具。

为什么单独一个模块：
  NL2SQL 接口是 **SSE 流**（POST /api/v1/query 返回 text/event-stream），
  请求体要求 db_id / session_id / user_id；这与通用 `_build_http_query_tool`
  的"POST /query + 立返 JSON"模型不兼容。

提供三个工具给代理 Teammate：
  - nl2sql_query           : 主查询（消费 SSE 流，拿到 result / done 事件）
  - nl2sql_list_databases  : 列出可用数据库
  - nl2sql_list_tables     : 列出指定数据库的表清单

设计要点：
  - **SSE 解析**：httpx 流式拉取，逐行解析 `data: {...}` 直到收到 result / done
  - **超时分层**：connect=10s 快失败；SSE read 不限（由 Runner 总超时兜底）
  - **session_id**：未显式传入则自动生成（uuid 短码）；同一 Teammate 多次调用
    若希望复用上下文，可由 Leader/Teammate 显式传同一个 session_id
  - **user_id**：默认 "generalist"，用作 NL2SQL 用户记忆隔离的标识
  - **日志**：请求 / SSE 事件 / 结果 / 错误 全程通过 nl2sql_log 打印
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.interface import log
from src.orchestration.proxy_tools import ProxyServiceConfig
from src.persistence.tool_truncate import truncate_for_persist


# ── 超时分层 ──────────────────────────────────────────────────────────


# 连接超时统一短设：服务未启动 / 端口错时立刻失败
_CONNECT_TIMEOUT = 10.0
_WRITE_TIMEOUT = 10.0
_POOL_TIMEOUT = 10.0
# SSE 流的 read 不限制（None），由 Runner 总超时兜底


# ── 入参 schema ───────────────────────────────────────────────────────


class _NL2SQLQueryArgs(BaseModel):
    question: str = Field(..., description="用户的自然语言问数描述")
    db_id: str = Field(..., description="目标数据库 id（如 'california_schools'）；可先调 nl2sql_list_databases 查看")
    session_id: Optional[str] = Field(None, description="会话 ID。复用同一个 ID 可让 NL2SQL 沿用上下文；不传则自动生成")
    user_id: Optional[str] = Field(None, description="用户标识，默认 'generalist'")
    timeout: Optional[int] = Field(None, description="超时秒数，默认走配置")


class _NL2SQLListTablesArgs(BaseModel):
    db_id: str = Field(..., description="数据库 id")


# ── 工具工厂 ──────────────────────────────────────────────────────────


def build_nl2sql_tools(svc: ProxyServiceConfig) -> list[BaseTool]:
    """根据 ProxyServiceConfig（access_kind='nl2sql_sse'）构造三个 NL2SQL 工具。"""
    return [
        _build_query_tool(svc),
        _build_list_databases_tool(svc),
        _build_list_tables_tool(svc),
    ]


def _build_query_tool(svc: ProxyServiceConfig) -> BaseTool:
    """主查询工具：POST /api/v1/query，消费 SSE 直至拿到结果。"""

    url = svc.base_url.rstrip("/") + "/api/v1/query"
    auth = svc.auth_header

    async def _call(
        question: str,
        db_id: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        sid = session_id or f"ga-{uuid.uuid4().hex[:8]}"
        body = {
            "query": question,
            "db_id": db_id,
            "session_id": sid,
            "user_id": user_id or "generalist",
        }
        headers = {"Accept": "text/event-stream"}
        if auth:
            headers["Authorization"] = auth

        # 超时分层：connect 短超时快失败；SSE read 不限
        client_timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=None,
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        )

        log.nl2sql_log(f"🡒 POST {url} db_id={db_id} session={sid} question={log.truncate(question, 80)}")

        result_payload: Optional[dict] = None
        error_payload: Optional[dict] = None
        done_payload: Optional[dict] = None
        candidate_stages: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    if resp.status_code >= 400:
                        text = await _safe_aread(resp)
                        log.nl2sql_log(f"✗ HTTP {resp.status_code}: {log.truncate(text, 200)}")
                        return {
                            "status": "error",
                            "http_status": resp.status_code,
                            "body": truncate_for_persist(text),
                        }
                    async for line in resp.aiter_lines():
                        if not line or line.startswith(":"):
                            # 空行或 SSE 心跳注释，跳过
                            continue
                        if not line.startswith("data: "):
                            continue
                        try:
                            evt = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue

                        etype = evt.get("type")
                        edata = evt.get("data") or {}

                        # SSE 事件分类型打日志（result 不展示完整 rows）
                        _log_sse_event(etype, edata)

                        if etype == "result":
                            result_payload = edata
                        elif etype == "error":
                            error_payload = edata
                        elif etype == "done":
                            done_payload = edata
                            # done 后服务端会关闭流；break 避免阻塞
                            break
                        elif etype == "stage":
                            node = edata.get("node")
                            if node:
                                candidate_stages.append(str(node))
        except httpx.ConnectError as e:
            reason = f"ConnectError: {e}（NL2SQL 服务似乎未启动 / 端口错 / 防火墙拦截）"
            log.nl2sql_log(f"✗ {reason}")
            return {"status": "error", "reason": reason, "session_id": sid}
        except httpx.TimeoutException as e:
            reason = f"{type(e).__name__}: {e}"
            log.nl2sql_log(f"✗ ⏱ {reason}")
            return {"status": "error", "reason": reason, "session_id": sid}
        except httpx.NetworkError as e:
            reason = f"{type(e).__name__}: {e}"
            log.nl2sql_log(f"✗ network: {reason}")
            return {"status": "error", "reason": reason, "session_id": sid}

        # 结果优先级：result > error > done
        if error_payload:
            reason = error_payload.get("error", "未知错误")
            log.nl2sql_log(f"✗ NL2SQL error event: {log.truncate(reason, 200)}")
            return {
                "status": "error",
                "reason": reason,
                "rejection": error_payload.get("rejection", False),
                "session_id": sid,
            }
        if result_payload:
            sql = result_payload.get("sql", "")
            rows = result_payload.get("result") or []
            rows_count = len(rows) if isinstance(rows, list) else "?"
            log.nl2sql_log(f"✓ done sql={log.truncate(sql, 80)} rows={rows_count}")
            return {
                "status": "ok",
                "sql": sql,
                "result": _truncate_rows(result_payload.get("result")),
                "session_id": sid,
                "query_id": result_payload.get("query_id", ""),
                "stages": candidate_stages,
            }
        if done_payload and not done_payload.get("has_result"):
            reason = done_payload.get("last_error") or "服务结束但未产生结果"
            log.nl2sql_log(f"✗ done without result: {log.truncate(reason, 200)}")
            return {
                "status": "error",
                "reason": reason,
                "fix_failed": done_payload.get("fix_failed", False),
                "session_id": sid,
            }
        log.nl2sql_log("✗ SSE 流结束但未收到 result / done 事件")
        return {"status": "error", "reason": "SSE 流结束但未收到 result / done 事件"}

    return StructuredTool.from_function(
        coroutine=_call,
        name="nl2sql_query",
        description=(
            "调用外部 NL2SQL 服务把自然语言问题转 SQL 并执行返回结果。"
            "必填：question（问题）、db_id（数据库 id）。"
            "可选：session_id（复用上下文）、user_id、timeout。"
            "返回 dict：成功时含 sql / result / session_id / query_id；失败时含 reason。"
        ),
        args_schema=_NL2SQLQueryArgs,
    )


def _build_list_databases_tool(svc: ProxyServiceConfig) -> BaseTool:
    """GET /api/v1/databases → 数据库清单。"""

    url = svc.base_url.rstrip("/") + "/api/v1/databases"
    auth = svc.auth_header
    timeout_default = svc.timeout

    async def _call() -> dict:
        headers = {"Authorization": auth} if auth else {}
        # 连接超时分层
        client_timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=float(timeout_default),
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        )
        log.nl2sql_log(f"🡒 GET {url}")
        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400:
                    log.nl2sql_log(f"✗ HTTP {resp.status_code}: {log.truncate(_safe_text(resp), 200)}")
                    return {"status": "error", "http_status": resp.status_code,
                            "body": _safe_text(resp)}
                data = resp.json()
                items = data.get("databases", [])
                names = [d.get("db_id") for d in items if d.get("db_id")]
                log.nl2sql_log(f"🡐 ✓ databases={names}")
                return {"status": "ok", "databases": names}
        except httpx.ConnectError as e:
            reason = f"ConnectError: {e}（NL2SQL 服务似乎未启动 / 端口错）"
            log.nl2sql_log(f"✗ {reason}")
            return {"status": "error", "reason": reason}
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            reason = f"{type(e).__name__}: {e}"
            log.nl2sql_log(f"✗ {reason}")
            return {"status": "error", "reason": reason}

    return StructuredTool.from_function(
        coroutine=_call,
        name="nl2sql_list_databases",
        description="列出 NL2SQL 服务可用的所有数据库 id。无参数。",
    )


def _build_list_tables_tool(svc: ProxyServiceConfig) -> BaseTool:
    """GET /api/v1/databases/{db_id}/tables → 表清单。"""

    base = svc.base_url.rstrip("/")
    auth = svc.auth_header
    timeout_default = svc.timeout

    async def _call(db_id: str) -> dict:
        url = f"{base}/api/v1/databases/{db_id}/tables"
        headers = {"Authorization": auth} if auth else {}
        client_timeout = httpx.Timeout(
            connect=_CONNECT_TIMEOUT,
            read=float(timeout_default),
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        )
        log.nl2sql_log(f"🡒 GET {url}")
        try:
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400:
                    log.nl2sql_log(f"✗ HTTP {resp.status_code}: {log.truncate(_safe_text(resp), 200)}")
                    return {"status": "error", "http_status": resp.status_code,
                            "body": _safe_text(resp)}
                data = resp.json()
                tables = data.get("tables", [])
                log.nl2sql_log(f"🡐 ✓ tables={tables}")
                return {"status": "ok", "db_id": data.get("db_id", db_id),
                        "tables": tables}
        except httpx.ConnectError as e:
            reason = f"ConnectError: {e}"
            log.nl2sql_log(f"✗ {reason}")
            return {"status": "error", "reason": reason}
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            reason = f"{type(e).__name__}: {e}"
            log.nl2sql_log(f"✗ {reason}")
            return {"status": "error", "reason": reason}

    return StructuredTool.from_function(
        coroutine=_call,
        name="nl2sql_list_tables",
        description="列出指定数据库的表清单。必填：db_id。",
        args_schema=_NL2SQLListTablesArgs,
    )


# ── SSE 事件日志摘要 ──────────────────────────────────────────────────


def _log_sse_event(etype: Optional[str], edata: dict) -> None:
    """按事件类型摘要打印 SSE 事件，避免刷屏。"""
    if not etype:
        return
    if etype == "stage":
        node = edata.get("node")
        status = edata.get("status", "")
        log.nl2sql_log(f"🡐 stage {node}{(' '+status) if status else ''}")
    elif etype == "llm_thinking":
        # 模型思考链 —— 太刷屏，只打首段省略后续
        text = edata.get("text", "")
        if text:
            log.nl2sql_log(f"🡐 llm_thinking: {log.truncate(text, 80)}")
    elif etype == "sql_candidates":
        n = len(edata.get("candidates") or [])
        log.nl2sql_log(f"🡐 sql_candidates n={n}")
    elif etype == "execution":
        ok = edata.get("success")
        log.nl2sql_log(f"🡐 execution success={ok} {log.truncate(edata.get('error', ''), 80)}")
    elif etype == "final_decision":
        sql = edata.get("selected_sql", "")
        log.nl2sql_log(f"🡐 final_decision sql={log.truncate(sql, 80)}")
    elif etype == "result":
        # 这里只摘要；最终汇总日志在主函数尾部
        pass
    elif etype == "error":
        log.nl2sql_log(f"🡐 error: {log.truncate(edata.get('error', ''), 200)}")
    elif etype == "done":
        log.nl2sql_log(f"🡐 done has_result={edata.get('has_result')}")
    else:
        # 其他类型简略带过
        log.nl2sql_log(f"🡐 {etype}")


# ── 辅助 ──────────────────────────────────────────────────────────────


def _safe_text(resp: httpx.Response) -> str:
    try:
        return resp.text
    except Exception:
        return resp.content.decode("utf-8", errors="replace")


async def _safe_aread(resp: httpx.Response) -> str:
    try:
        await resp.aread()
        return resp.text
    except Exception:
        return ""


# 返回行数过多时截断（防止 LLM context 爆掉）
_MAX_ROWS_PREVIEW = 20


def _truncate_rows(rows):
    """把返回结果截到 _MAX_ROWS_PREVIEW，并附 total_rows 提示。"""
    if not isinstance(rows, list):
        return rows
    if len(rows) <= _MAX_ROWS_PREVIEW:
        return rows
    return {
        "preview_rows": rows[:_MAX_ROWS_PREVIEW],
        "total_rows": len(rows),
        "note": f"原始结果 {len(rows)} 行，仅展示前 {_MAX_ROWS_PREVIEW} 行",
    }
