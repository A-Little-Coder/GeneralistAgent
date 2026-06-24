"""
Demo 02: AsyncSqliteSaver —— 落盘 + 跨进程恢复。

跑法：
    python learn/05-memory-persistence/02-sqlite-saver/demo_sqlite_resume.py

观察点：
  1. AsyncSqliteSaver(conn) + await saver.setup() 建表
  2. "关闭 saver → 重开同一文件" 模拟跨进程，历史能恢复
  3. await saver.adelete_thread(thread_id) 清掉某 session

⚠️ 重要：项目用的是 **AsyncSqliteSaver**（不是 SqliteSaver）。
   因为 cli.py 走 asyncio + agent.astream，同步的 SqliteSaver 调 astream 会抛 NotImplementedError。

数据库放在脚本同目录的临时文件，跑完会自动清理。
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
    model = GenericFakeChatModel(messages=iter(replies))

    async def call_model(state: ChatState):
        resp = await model.ainvoke(state["messages"])
        return {"messages": [resp]}

    g = StateGraph(ChatState)
    g.add_node("chat", call_model)
    g.set_entry_point("chat")
    g.set_finish_point("chat")
    return g.compile(checkpointer=saver)


async def _open_saver(db_path: str) -> tuple[AsyncSqliteSaver, aiosqlite.Connection]:
    """打开 db 文件，返回 (saver, connection)。"""
    conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn


async def main():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="demo-sqlite-")
    os.close(fd)
    try:
        # ── 进程 1：写入 ──
        print("=== 写入阶段（进程模拟 1）===")
        saver1, conn1 = await _open_saver(db_path)
        try:
            app1 = _build_app(saver1, replies=[AIMessage(content="好的，已记住你叫张三")])
            cfg = {"configurable": {"thread_id": "leader-session-1"}}
            state = await app1.ainvoke(
                {"messages": [HumanMessage(content="我叫张三")]}, cfg,
            )
            print("  AI:", state["messages"][-1].content)
        finally:
            print("  关闭 saver 与连接")
            await conn1.close()

        # ── 进程 2：用全新对象重新打开同一文件 ──
        print("\n=== 恢复阶段（进程模拟 2 —— 重新打开同一文件）===")
        saver2, conn2 = await _open_saver(db_path)
        try:
            app2 = _build_app(saver2, replies=[AIMessage(content="你叫张三")])
            cfg = {"configurable": {"thread_id": "leader-session-1"}}
            # 只发新消息，历史由 saver2 从磁盘加载
            state = await app2.ainvoke(
                {"messages": [HumanMessage(content="我叫什么名字？")]}, cfg,
            )
            print("  AI:", state["messages"][-1].content, "✓ 跨\"进程\"恢复成功！")
            print(f"  历史长度: {len(state['messages'])}（两轮 Human + 两轮 AI）")

            # 看看数据库里现在有多少 checkpoint
            cur = await conn2.execute("SELECT COUNT(*) FROM checkpoints")
            n = (await cur.fetchone())[0]
            print(f"  checkpoints 表当前 {n} 行（一个 session 对应多个 checkpoint）")
            await cur.close()

            # 演示 adelete_thread —— /delete <session> 的底层
            print("\n=== 删除 thread_id（对应项目 /delete <session>）===")
            await saver2.adelete_thread("leader-session-1")
            cur = await conn2.execute("SELECT COUNT(*) FROM checkpoints")
            n_after = (await cur.fetchone())[0]
            await cur.close()
            print(f"  adelete_thread 后剩 {n_after} 行")
        finally:
            await conn2.close()
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
