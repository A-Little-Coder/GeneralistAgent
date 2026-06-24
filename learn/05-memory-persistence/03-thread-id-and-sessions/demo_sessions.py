"""
Demo 03: thread_id + 多 session —— 同库不同 thread_id 互不串台。

跑法：
    python learn/05-memory-persistence/03-thread-id-and-sessions/demo_sessions.py

观察点：
  1. 同一 AsyncSqliteSaver，3 个 thread_id 互相隔离
  2. 切 thread_id == 切话题
  3. adelete_thread 只影响目标 session
  4. sessions.json + leader.db 一起跨"进程"恢复

不需要 API Key —— GenericFakeChatModel 喂死回复。
"""

import asyncio
import os
import tempfile
from typing import TypedDict

import aiosqlite
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated


class ChatState(TypedDict):
    messages: Annotated[list, add_messages]


def _build_app(saver: AsyncSqliteSaver, replies):
    """每个 session 一个 model 实例（fake model 是有状态的，复用就乱了）。"""
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
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="demo-sessions-")
    os.close(fd)
    try:
        # ── 1. 新建 3 个 session 并各写一条 ──
        print("=== 新建 3 个 session 并各写一条 ===")
        conn = await aiosqlite.connect(db_path)
        saver = AsyncSqliteSaver(conn)
        await saver.setup()

        sessions = {
            "session-1": ("张三", "好，记住你叫张三"),
            "session-2": ("李四", "好，记住你叫李四"),
            "session-3": ("王五", "好，记住你叫王五"),
        }
        for sid, (name, reply) in sessions.items():
            app = _build_app(saver, replies=[AIMessage(content=reply)])
            cfg = {"configurable": {"thread_id": sid}}
            await app.ainvoke(
                {"messages": [HumanMessage(content=f"我叫{name}")]}, cfg,
            )
            print(f"  {sid}: {name}")

        # ── 2. 切回 session-1 验证隔离 ──
        print("\n=== 切换回 session-1 验证隔离 ===")
        cfg = {"configurable": {"thread_id": "session-1"}}
        cp = await saver.aget_tuple(cfg)
        msgs = cp.checkpoint["channel_values"]["messages"]
        print(f"  当前 session: session-1")
        names_in_history = [m.content for m in msgs if hasattr(m, "content")]
        print(f"  当前 thread_id 的历史内容: {names_in_history}")
        print(f"  ← session-1 只看得到自己写过的'我叫张三'，没有李四王五")

        # ── 3. 删除 session-2 ──
        print("\n=== 删除 session-2（联动 purge）===")
        cur = await conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
        before = sorted(r[0] for r in await cur.fetchall())
        await cur.close()
        print(f"  删除前: {before}")

        await saver.adelete_thread("session-2")

        cur = await conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
        after = sorted(r[0] for r in await cur.fetchall())
        await cur.close()
        print(f"  删除后: {after}")

        await conn.close()

        # ── 4. 重新打开模拟跨进程 ──
        print("\n=== 跨\"进程\"重开，状态恢复 ===")
        conn2 = await aiosqlite.connect(db_path)
        saver2 = AsyncSqliteSaver(conn2)
        await saver2.setup()
        cur = await conn2.execute("SELECT DISTINCT thread_id FROM checkpoints")
        recovered = sorted(r[0] for r in await cur.fetchall())
        await cur.close()
        print(f"  恢复后 thread_id 列表: {recovered}  ✓ session-1 / session-3 还在")
        await conn2.close()
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
