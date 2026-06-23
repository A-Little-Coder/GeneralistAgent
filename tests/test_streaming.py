"""
流式输出测试用例 — 覆盖 StreamRenderer 渲染与 rebuild_state 重建。

覆盖场景（对应 specs/streaming-output）：
  1. 逐 token 输出
  2. 工具调用流式可见（tool_call_chunks 首片段打印工具名）
  3. 节点更新可见（updates 模式）
  4. 工具返回展示
  5. 重建完整消息列表（AI + Tool 顺序正确）
  6. 多轮上下文连续（state 携带历史）
  7. 多工具调用链重建
  8. 异步启动 + 真实 graph 流式
"""

import asyncio
import io
from contextlib import redirect_stdout

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from src.interface.cli import StreamRenderer, rebuild_state


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


# ── 渲染：updates 模式（工具返回 + 节点） ────────────────────────────

class TestRenderUpdates:
    """updates 模式渲染与收集。"""

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
        # 截断到 300
        assert "x" * 300 in text
        assert "x" * 400 not in text

    def test_non_message_state_collected(self):
        """非 messages 键（如 todos）按 last-write-wins 收集。"""
        renderer = StreamRenderer()
        renderer.handle("updates", {"agent": {"todos": [{"task": "a"}]}})
        renderer.handle("updates", {"agent": {"todos": [{"task": "b"}]}})
        assert renderer.collected_state["todos"] == [{"task": "b"}]


# ── state 重建 ───────────────────────────────────────────────────────

class TestRebuildState:
    """流式后手动重建 state。"""

    def test_rebuild_complete_messages(self):
        """AI 消息 + Tool 消息顺序正确写入 state。"""
        renderer = StreamRenderer()
        ai = AIMessage(content="我来查一下", tool_calls=[{"name": "search", "args": {"q": "x"}, "id": "1"}])
        tool = ToolMessage(content="结果", tool_call_id="1", name="search")
        ai2 = AIMessage(content="查到了：结果")
        renderer.handle("updates", {"agent": {"messages": [ai]}})
        renderer.handle("updates", {"tools": {"messages": [tool]}})
        renderer.handle("updates", {"agent": {"messages": [ai2]}})

        input_state = {"messages": [HumanMessage(content="查 x")]}
        new_state = rebuild_state(input_state, renderer)

        assert new_state["messages"] == [HumanMessage(content="查 x"), ai, tool, ai2]

    def test_multi_tool_chain_rebuild(self):
        """多工具调用链：两次 tool_calls + 两个 ToolMessage 顺序正确。"""
        renderer = StreamRenderer()
        ai1 = AIMessage(content="", tool_calls=[
            {"name": "f1", "args": {}, "id": "1"},
            {"name": "f2", "args": {}, "id": "2"},
        ])
        t1 = ToolMessage(content="r1", tool_call_id="1", name="f1")
        t2 = ToolMessage(content="r2", tool_call_id="2", name="f2")
        ai2 = AIMessage(content="汇总")
        for node, msgs in [("agent", [ai1]), ("tools", [t1, t2]), ("agent", [ai2])]:
            renderer.handle("updates", {node: {"messages": msgs}})

        new_state = rebuild_state({"messages": []}, renderer)
        assert new_state["messages"] == [ai1, t1, t2, ai2]

    def test_multi_turn_continuity(self):
        """多轮：上一轮 state 历史被携带到下一轮。"""
        history = [HumanMessage(content="我叫张三"), AIMessage(content="你好张三")]
        renderer = StreamRenderer()
        renderer.handle("updates", {"agent": {"messages": [AIMessage(content="有什么帮你的")]}}, )

        new_state = rebuild_state({"messages": history + [HumanMessage(content="你好")]}, renderer)
        # 历史 + 本轮用户 + 本轮 AI
        assert len(new_state["messages"]) == 4
        assert new_state["messages"][0].content == "我叫张三"


# ── 异步端到端：真实 graph + fake 流式模型 ────────────────────────────

class TestAsyncStreamingIntegration:
    """真实 compiled graph + 流式 fake model，验证 astream 与重建。"""

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

    def test_async_stream_tokens_and_rebuild(self):
        """astream 流式输出经渲染器，rebuild_state 拿到完整消息。"""
        # 单条消息；token 级多片段渲染由 test_token_by_token_output 覆盖
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
        # 重建出完整 AIMessage
        new_state = rebuild_state({"messages": [HumanMessage(content="hi")]}, renderer)
        assert len(new_state["messages"]) == 2
        assert isinstance(new_state["messages"][1], AIMessage)
        assert new_state["messages"][1].content == "你好，世界"

    def test_main_uses_asyncio_run(self):
        """main() SHALL 用 asyncio.run 启动（异步入口）。"""
        import inspect
        from src.interface.cli import repl
        assert inspect.iscoroutinefunction(repl)
        import src.main as main_mod
        assert hasattr(main_mod, "asyncio")
