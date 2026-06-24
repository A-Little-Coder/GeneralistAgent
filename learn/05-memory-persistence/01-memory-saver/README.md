# 01. MemorySaver —— RAM 内的最小持久化

## 这一节解决的问题

LangGraph 默认的 graph 是**无状态**的：每次 `invoke` / `astream` 都从你传的 `state` 开始。如果你想要"记住前一轮说过什么"，要么自己手工拼接 messages 列表（容易拼错、容易丢），要么交给 LangGraph 的 **checkpointer**。

`MemorySaver` 是最简单的 checkpointer —— 把 state 存在 **进程内的字典里**，按 `thread_id` 索引：

```
   astream({"messages":[新消息]}, config={"thread_id":"abc"})
                            │
                            ▼
              ┌──────────────────────────┐
              │   MemorySaver (RAM dict) │
              │   {                      │
              │     "abc": [hist...]     │  ← 自动加载历史
              │   }                      │
              └──────────────────────────┘
                            │
                            ▼
        合并：历史 + 新消息 → 送进 graph 推理
                            │
                            ▼
        推理结果 → 写回 MemorySaver["abc"]
```

## 关键 API

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

saver = MemorySaver()

graph = StateGraph(...)
# ...
app = graph.compile(checkpointer=saver)

# 同一个 thread_id 跨多次调用 → 记忆贯通
app.invoke({"messages": [...]}, config={"configurable": {"thread_id": "user-1"}})
```

要点：
- `thread_id` 就是"会话标识"，相同 thread_id 共享同一份 state
- 每次调用只传**新增**消息，LangGraph 自动用 `add_messages` reducer 把旧消息接上
- 进程退出 → 字典随之销毁，所以叫"RAM only"

## demo 在做什么

`demo_memory_saver.py` 做了三件事：

1. 构造一个会回答 `"我已经记住了你叫 <name>"` 的最小图
2. 第一轮告诉它 "我叫张三"
3. 第二轮**只发** "我叫什么名字"，看它能不能答上 "张三"

> 没有用真实 LLM，用 `GenericFakeChatModel` 喂死消息 —— 焦点是 saver 的行为，不是模型能力。

## 跑

```bash
python learn/05-memory-persistence/01-memory-saver/demo_memory_saver.py
```

预期输出大致：

```
=== 第一轮（thread_id=user-1） ===
  你: 我叫张三
  AI: 好的，我已经记住了你叫张三

=== 第二轮（同一 thread_id；不再重发"我叫张三"） ===
  你: 我叫什么名字？
  AI: 你叫张三
  历史长度: 4  (两条 Human + 两条 AI)

=== 第三轮（换 thread_id=user-2）===
  你: 我叫什么名字？
  AI: 抱歉我不知道
  历史长度: 2  (新 thread_id 没有历史)
```

注意第三段 —— **换了 thread_id 就是另一个会话**，互不可见。这一条直接对应项目里"不同 Teammate 用不同 thread_id 不串台"。

## 接下来

- `02-sqlite-saver/` 把 saver 换成 `SqliteSaver`，进程退出再启动还能恢复
- `03-thread-id-sessions/` 把"换 thread_id 隔离"扩展为完整的多 session 模型
