"""
Demo 04: Teammate vs Leader —— 双层记忆边界。

跑法：
    python learn/05-memory-persistence/04-teammate-vs-leader/demo_two_tier_memory.py

观察点：
  1. Leader 用 AsyncSqliteSaver（落盘）；Teammate 用 MemorySaver（RAM）
  2. Teammate 同一 thread_id 多次调用共享记忆
  3. 不同 Teammate 互相不可见（独立 MemorySaver）
  4. leader.db 中只有 Leader 的 thread_id，不含 teammate_id
"""

import asyncio
import os
import tempfile
from typing import TypedDict

import aiosqlite
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_app(saver, replies):
    """每个 Teammate 各起一个 graph，model 灌入预设回复。"""
    model = GenericFakeChatModel(messages=iter(replies))

    async def call_model(state: ChatState):
        resp = await model.ainvoke(state["messages"])
        return {"messages": [resp]}

    g = StateGraph(ChatState)
    g.add_node("chat", call_model)
    g.set_entry_point("chat")
    g.set_finish_point("chat")
    return g.compile(checkpointer=saver)


async def main():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="demo-two-tier-")
    os.close(fd)
    try:
        # ── Leader（AsyncSqliteSaver）──
        leader_conn = await aiosqlite.connect(db_path)
        leader_saver = AsyncSqliteSaver(leader_conn)
        await leader_saver.setup()

        print("=== Leader 写一句进 SqliteSaver ===")
        leader_app = _build_app(leader_saver, replies=[AIMessage(content="好的张三")])
        await leader_app.ainvoke(
            {"messages": [HumanMessage(content="我叫张三")]},
            {"configurable": {"thread_id": "session-1"}},
        )
        print("  Leader.session-1: 我叫张三 → 落盘")

        # ── Teammate A（独立 MemorySaver）──
        print("\n=== Teammate A：两次消息共享记忆 ===")
        a_saver = MemorySaver()
        a_app = _build_app(
            a_saver,
            replies=[AIMessage(content="A 收到，先做 X"),
                     AIMessage(content="A 继续，接着 Y")],
        )
        a_cfg = {"configurable": {"thread_id": "teammate-A@main"}}
        await a_app.ainvoke({"messages": [HumanMessage(content="先做 X")]}, a_cfg)
        print("  Teammate A turn1: 先做 X")
        state = await a_app.ainvoke({"messages": [HumanMessage(content="再做 Y")]}, a_cfg)
        print("  Teammate A turn2: 再做 Y")
        print(f"  Teammate A 历史长度: {len(state['messages'])} ✓ 累积了")

        # ── Teammate B（独立 MemorySaver）──
        print("\n=== Teammate B：独立 MemorySaver ===")
        b_saver = MemorySaver()
        b_app = _build_app(b_saver, replies=[AIMessage(content="B 收到")])
        state = await b_app.ainvoke(
            {"messages": [HumanMessage(content="hi B")]},
            {"configurable": {"thread_id": "teammate-B@main"}},
        )
        print(f"  Teammate B 历史长度: {len(state['messages'])} ✓ 看不到 A 的内容")

        # ── 验证 leader.db 没有 teammate 的 thread_id ──
        print("\n=== leader.db 中的 thread_id ===")
        cur = await leader_conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
        ids = sorted(r[0] for r in await cur.fetchall())
        await cur.close()
        print(f"  {ids}  ← 仅 Leader，不含 teammate_id")

        await leader_conn.close()
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
