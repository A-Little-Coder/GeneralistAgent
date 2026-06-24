"""
3.4 端到端集成测试：mock 问数服务 + 代理 Teammate + Runner 真实流程。

验证链路：
  Leader (模拟方式) 通过 Mailbox 给 Teammate 发任务
  -> Runner 收到 → build agent → 调 chatbi_query (HTTP, 打到 mock server)
  -> Teammate 通过 SendMessage 回 Leader

为避免依赖真实 LLM，本测试用一个**伪 agent**：拦截 build_agent_for_prompt 返回
一个 fake，由 fake 直接调用 tool（绕过 LLM 决策），从而验证：
  1) 代理工具确实绑定到 Teammate
  2) HTTP 请求真正打到 mock 服务并拿到响应
  3) Runner 的 idle 循环能正确触发工具调用并把结果回写 last_output
"""

from __future__ import annotations

import asyncio
import json
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.orchestration.mailbox import Mailbox, Message
from src.orchestration.proxy_tools import ProxyServiceConfig
from src.orchestration.runner import Runner
from src.orchestration.task_list import TaskList
from src.orchestration.teammate import Teammate, create_proxy_teammate


# ── mock HTTP server ──────────────────────────────────────────────────


class _MockChatBIHandler(BaseHTTPRequestHandler):
    """模拟 ChatBI 的最小 HTTP server —— /query POST 接口。"""

    def do_POST(self):  # noqa: N802
        if self.path != "/query":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        question = body.get("question", "")

        resp = {
            "status": "ok",
            "sql": f"SELECT * FROM sales WHERE q = '{question}'",
            "rows": [{"region": "华东", "amount": 12345}],
        }
        payload = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass  # 静默


@pytest.fixture
def mock_chatbi_server():
    """启动 mock HTTP server，yield (host, port)。"""
    server = HTTPServer(("127.0.0.1", 0), _MockChatBIHandler)
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


# ── fake agent：直接调工具，绕过 LLM ──────────────────────────────────


class _FakeProxyAgent:
    """模拟代理 Teammate 的 agent：收到 prompt 后直接调第一个 chatbi 工具。"""

    def __init__(self, tools):
        self._tools = tools
        # 找 chatbi_query 工具
        self._chatbi_tool = next((t for t in tools if "query" in t.name), None)
        assert self._chatbi_tool is not None, "未找到 chatbi_query 工具"

    async def astream(self, state, config=None, stream_mode=None):
        """模拟 deepagents 的 astream：调用工具，再 yield 一条 AIMessage。"""
        messages = state.get("messages", [])
        user_text = messages[-1].content if messages else "默认问题"

        tool_result = await self._chatbi_tool.ainvoke({"question": user_text})

        # 模拟 deepagents 的 updates 模式输出
        final = AIMessage(
            content=f"查询完成。SQL: {tool_result.get('sql')}；行数={len(tool_result.get('rows', []))}"
        )
        yield ("updates", {"agent": {"messages": [final]}})


# ── 端到端测试 ────────────────────────────────────────────────────────


async def test_e2e_proxy_teammate_calls_mock_chatbi(mock_chatbi_server, tmp_path):
    """完整链路：投递任务 → Runner 跑 → 工具打到 mock → last_output 拿到结果。"""

    # 1) 配置代理服务，指向 mock server
    svc = ProxyServiceConfig(
        name="chatbi",
        access_kind="http",
        base_url=mock_chatbi_server,
        timeout=10,
    )

    # 2) 创建代理 Teammate（用 GenericFakeChatModel 作为占位，不会被调用）
    skills_root = tmp_path / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    (skills_root / "proxy_chatbi").mkdir(parents=True, exist_ok=True)
    (skills_root / "proxy_chatbi" / "SKILL.md").write_text(
        "---\nname: proxy_chatbi\n---\n占位 SKILL", encoding="utf-8"
    )

    fallback = GenericFakeChatModel(messages=iter([]))
    teammate = create_proxy_teammate(
        name="proxy_chatbi_runner",
        team_name="e2e-team",
        service=svc,
        skills_root=str(skills_root),
        fallback_model=fallback,
    )

    # 3) 替换 build_agent_for_prompt 为 fake agent —— 验证工具能真正调用 mock
    teammate.build_agent_for_prompt = lambda base_prompt="", checkpointer=None: _FakeProxyAgent(teammate.tools)  # type: ignore

    # 4) 启动 Runner
    mailbox = Mailbox()
    task_list = TaskList(base_dir=tmp_path / "teams", team_name="e2e-team")
    runner = Runner(teammate=teammate, mailbox=mailbox, task_list=task_list,
                    idle_interval=0.05)
    runner.start()

    try:
        # 5) 投递任务到 Mailbox
        await mailbox.send(Message(
            sender="leader",
            to=teammate.name,
            content="近 7 天华东大区销售总额",
            kind="task_assigned",
        ))

        # 6) 等 Runner 处理
        for _ in range(40):  # 最多 2s
            await asyncio.sleep(0.05)
            if runner.last_output:
                break

        assert runner.last_output, "Runner 未产生输出"
        # mock server 返回的 SQL 内容应出现在 Runner 输出中
        assert "SELECT * FROM sales" in runner.last_output
        assert "行数=1" in runner.last_output
    finally:
        await runner.request_shutdown()
        await runner.wait_done()
