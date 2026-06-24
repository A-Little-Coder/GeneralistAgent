# 02. AsyncSqliteSaver —— 落盘 + 跨进程恢复

## 这一节解决的问题

`MemorySaver` 一退出就什么都没了。要让 Leader 在重启 CLI 后还记得"昨天聊到哪了"，必须把 checkpoint 写到磁盘上。

LangGraph 官方的 SQLite 持久化分两种实现：

| 类                  | 用于什么                            | 备注                                   |
|---------------------|------------------------------------|----------------------------------------|
| `SqliteSaver`       | **同步** API（`app.invoke`）        | 调 `astream` 会抛 NotImplementedError  |
| `AsyncSqliteSaver`  | **异步** API（`app.astream/ainvoke`）| 项目里 CLI 走 asyncio → 必须用它       |

→ 项目 `LeaderStore` 用的是 **AsyncSqliteSaver**。

```python
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

conn = await aiosqlite.connect("memory/leader.db")
saver = AsyncSqliteSaver(conn)
await saver.setup()    # 首次建表（幂等）

# 然后正常 build_graph：
app = graph.compile(checkpointer=saver)
async for mode, data in app.astream(..., config={"configurable":{"thread_id":"sess-1"}}, ...):
    ...
```

## 表结构（peek 一下）

```
checkpoints
┌──────────────┬──────────────┬───────────────┬──────┬─────────┐
│ thread_id    │ checkpoint_ns│ checkpoint_id │ ...  │ blob    │
├──────────────┼──────────────┼───────────────┼──────┼─────────┤
│ session-1    │ ""           │ ckpt-001      │      │ <pickle>│
│ session-1    │ ""           │ ckpt-002      │      │ <pickle>│
│ session-2    │ ""           │ ckpt-003      │      │ <pickle>│
└──────────────┴──────────────┴───────────────┴──────┴─────────┘

writes（中间写入的 channel 增量）
┌──────────────┬───────────────┬──────────┬─────────────────┐
│ thread_id    │ checkpoint_id │ channel  │ value           │
└──────────────┴───────────────┴──────────┴─────────────────┘
```

- 一个 `thread_id` 可能有**多个 checkpoint**（每一步都会留一个，便于回滚）
- 读最新 state 时 LangGraph 取 `thread_id` 对应的最后一行
- 删某个 session 的全部历史 = `adelete_thread(thread_id)` —— 项目里 `LeaderStore.purge` 就是封装它

## demo 在做什么

`demo_sqlite_resume.py`：

1. 用 `tmp_path/leader.db` 做存储
2. **第一次**运行 graph，告诉它"我叫张三"
3. **关掉** saver 与连接
4. **重新打开**同一文件，**新建** graph，问"我叫什么名字"
5. 验证仍能答出"张三"
6. 演示 `adelete_thread` 清掉该 session

## 跑

```bash
python learn/05-memory-persistence/02-sqlite-saver/demo_sqlite_resume.py
```

预期输出：

```
=== 写入阶段（进程模拟 1）===
  AI: 好的，已记住你叫张三
  关闭 saver 与连接

=== 恢复阶段（进程模拟 2 —— 重新打开同一文件）===
  AI: 你叫张三 ✓ 跨"进程"恢复成功！
  历史长度: 4（两轮 Human + 两轮 AI）
  checkpoints 表当前 6 行（一个 session 对应多个 checkpoint）

=== 删除 thread_id（对应项目 /delete <session>）===
  adelete_thread 后剩 0 行
```

## 在项目里的位置

`src/persistence/leader_store.py::LeaderStore` 把上面的样板包成可复用模块：

```python
store = await LeaderStore.create()           # 等价于 connect + setup
saver = store.get_checkpointer()             # 注入到 build_agent
await store.purge("session-2")               # 等价于 adelete_thread
await store.aclose()                         # 关连接
```

