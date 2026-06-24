"""
Demo 01: MemorySaver —— RAM 内的最小持久化。

跑法：
    python learn/05-memory-persistence/01-memory-saver/demo_memory_saver.py

观察点：
  1. 同一个 thread_id 跨多次 invoke → 记忆自动贯通
  2. 不同 thread_id 互相隔离
  3. 调用者只传新消息，历史由 saver 加载

不需要 API Key —— 用 GenericFakeChatModel 喂死回复。
"""

import asyncio
from typing import TypedDict

from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import Annotated


# ── 1. 定义图状态：messages 用 add_messages reducer 自动拼接 ──────


class ChatState(TypedDict):
    """messages 字段用 add_messages —— 新增消息会被 append 到历史末尾。"""
    messages: Annotated[list, add_messages]


# ── 2. 一个 fake model：根据预设序列依次回答 ──────────────────────


def _make_fake_model_replies():
    return iter([
        AIMessage(content="好的，我已经记住了你叫张三"),  # 第一轮
        AIMessage(content="你叫张三"),                   # 第二轮（同一会话）
        AIMessage(content="抱歉我不知道"),                # 第三轮（新会话）
    ])


def build_app(saver: MemorySaver):
    model = GenericFakeChatModel(messages=_make_fake_model_replies())

    async def call_model(state: ChatState):
        resp = await model.ainvoke(state["messages"])
        return {"messages": [resp]}

    g = StateGraph(ChatState)
    g.add_node("chat", call_model)
    g.set_entry_point("chat")
    g.set_finish_point("chat")
    return g.compile(checkpointer=saver)


# ── 3. 演示主流程 ────────────────────────────────────────────────


async def main():
    saver = MemorySaver()
    app = build_app(saver)

    # ── 第一轮：user-1 自我介绍 ──
    print("=== 第一轮（thread_id=user-1） ===")
    cfg1 = {"configurable": {"thread_id": "user-1"}}
    state = await app.ainvoke({"messages": [HumanMessage(content="我叫张三")]}, cfg1)
    print("  你:", "我叫张三")
    print("  AI:", state["messages"][-1].content)

    # ── 第二轮：同一 thread_id，不再重发首句 ──
    print("\n=== 第二轮（同一 thread_id；不再重发首句）===")
    state = await app.ainvoke({"messages": [HumanMessage(content="我叫什么名字？")]}, cfg1)
    print("  你:", "我叫什么名字？")
    print("  AI:", state["messages"][-1].content)
    print("  历史长度:", len(state["messages"]),
          " (两条 Human + 两条 AI)")

    # ── 第三轮：换 thread_id，应彻底不知道"张三" ──
    print("\n=== 第三轮（换 thread_id=user-2）===")
    cfg2 = {"configurable": {"thread_id": "user-2"}}
    state = await app.ainvoke({"messages": [HumanMessage(content="我叫什么名字？")]}, cfg2)
    print("  你:", "我叫什么名字？")
    print("  AI:", state["messages"][-1].content)
    print("  历史长度:", len(state["messages"]),
          " (新 thread_id 没有历史)")

    # ── 把内部状态打印出来 ──
    print("\n=== 进程内 MemorySaver 当前持有的 thread_id ===")
    tuples = list(saver.list(None))
    threads = sorted({t.config["configurable"]["thread_id"] for t in tuples})
    print("  ", threads)


if __name__ == "__main__":
    asyncio.run(main())
