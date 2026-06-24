"""
流式输出测试用例 — 覆盖 StreamRenderer 渲染（add-memory-persistence 之后）。

add-memory-persistence 把"流式后手动重建对话状态"从 streaming-output 能力中移除。
历史由 LangGraph SqliteSaver 按 thread_id 自动加载与落盘，CLI 不再维护
rebuild_state / collected_messages / collected_state。

覆盖场景（对应 specs/streaming-output 的 ADDED / MODIFIED 部分）：
  1. 逐 token 输出
  2. 工具调用流式可见（tool_call_chunks 首片段打印工具名）
  3. 工具返回展示（updates 模式预览）
  4. 异步入口（repl 是 coroutine）
  5. astream + 真实 fake graph 端到端
"""

import asyncio
import io
from contextlib import redirect_stdout

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from src.interface.cli import StreamRenderer


# ── 渲染：逐 token + 工具调用 ────────────────────────────────────────


class TestRenderMessages:
    """messages 模式渲染。"""

    def test_token_by_token_output(self):
        renderer = StreamRenderer()
        out = io.StringIO()
        with redirect_stdout(out):
            renderer.handle("messages", (AIMessageChunk(content="你"), {}))
            renderer.handle("messages", (AIMessageChunk(content="好"), {}))
        assert "你好" in out.getvalue()

    def test_tool_call_name_printed_once(self):
        renderer = StreamRenderer()
        out = io.StringIO()
        with redirect_stdout(out):
            # 首片段携带工具名
            renderer.handle("messages", (
                AIMessageChunk(content="", tool_call_chunks=[
                    {"name": "search", "args": '{"q":', "id": "1", "index": 0, "type": "tool_call_chunk"}
                ]),
                {"langgraph_node": "agent"},
            ))
            # 后续片段仅追加 args，不再重复打印工具名
            renderer.handle("messages", (
                AIMessageChunk(content="", tool_call_chunks=[
                    {"name": None, "args": '"data"}', "id": "1", "index": 0, "type": "tool_call_chunk"}
                ]),
                {"langgraph_node": "agent"},
            ))
        text = out.getvalue()
        assert "🛠 调用工具: search" in text
        # 工具名只出现一次
        assert text.count("🛠 调用工具: search") == 1


# ── 渲染：updates 模式（工具返回预览） ────────────────────────────────


class TestRenderUpdates:
    """updates 模式渲染：现在仅做预览打印，不再收集状态。"""

    def test_tool_return_displayed_and_truncated(self):
        renderer = StreamRenderer()
        long_content = "x" * 1000
        out = io.StringIO()
        with redirect_stdout(out):
            renderer.handle("updates", {"tools": {"messages": [
                ToolMessage(content=long_content, tool_call_id="1", name="search"),
            ]}})
        text = out.getvalue()
        assert "📥 工具返回:" in text
        # 截断到 300（预览长度）
        assert "x" * 300 in text
        assert "x" * 400 not in text

    def test_no_rebuild_state_export(self):
        """rebuild_state 已被移除（REMOVED Requirement）—— 防止后续不慎复活。"""
        from src.interface import cli
        assert not hasattr(cli, "rebuild_state"), "rebuild_state 应已删除"

    def test_renderer_does_not_collect_state(self):
        """StreamRenderer 不再维护 collected_messages / collected_state。"""
        renderer = StreamRenderer()
        assert not hasattr(renderer, "collected_messages")
        assert not hasattr(renderer, "collected_state")


# ── 异步端到端：真实 graph + fake 流式模型 ────────────────────────────


class TestAsyncStreamingIntegration:
    """真实 compiled graph + 流式 fake model，验证 astream 渲染。"""

    def _build_graph(self, messages_iter):
        """构造一个单 LLM 节点的最小 graph，模型从迭代器吐 chunk。"""
        from langchain_core.language_models import GenericFakeChatModel
        from langgraph.graph import StateGraph
        from typing import TypedDict

        class S(TypedDict):
            messages: list

        model = GenericFakeChatModel(messages=iter(messages_iter))

        async def call_model(state):
            resp = await model.ainvoke(state["messages"])
            return {"messages": [resp]}

        g = StateGraph(S)
        g.add_node("call", call_model)
        g.set_entry_point("call")
        g.set_finish_point("call")
        return g.compile()

    def test_async_stream_tokens(self):
        """astream 流式输出经渲染器打印出完整文本。"""
        chunks = [AIMessage(content="你好，世界")]
        app = self._build_graph(chunks)

        renderer = StreamRenderer()
        out = io.StringIO()

        async def run():
            async for mode, data in app.astream(
                {"messages": [HumanMessage(content="hi")]},
                stream_mode=["messages", "updates"],
            ):
                with redirect_stdout(out):
                    renderer.handle(mode, data)

        asyncio.run(run())

        text = out.getvalue()
        assert "你好" in text and "世界" in text

    def test_main_uses_asyncio_run(self):
        """main() SHALL 用 asyncio.run 启动（异步入口）。"""
        import inspect
        from src.interface.cli import repl
        assert inspect.iscoroutinefunction(repl)
        import src.main as main_mod
        assert hasattr(main_mod, "asyncio")
