# 03. thread_id 与多 Session

## 这一节解决的问题

`thread_id` 是 LangGraph checkpointer 的**唯一索引键**。同库不同 thread_id 互不可见 —— 这正是"多会话切换"的根基。

```
                           leader.db
                              │
       ┌──────────┬──────────┼──────────┬──────────┐
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
   session-1  session-2  session-3  session-4  session-5
   "张三"      "李四"      "(空)"     "退保"      "工单"

   不同 thread_id 互相完全隔离
   切 thread_id 就是切话题
```

项目里 `SessionManager` 负责：

- 给每个 session 分配 id (`session-1` / `session-2` / ...)
- 维护"当前 session"指针
- 用 SessionManager 取出 current.id → 喂给 `agent.astream(config={"thread_id": current.id})`

`memory/sessions.json` 文件结构：

```json
{
  "current": "session-2",
  "sessions": [
    {"id": "session-1", "title": "查 Q1 销售", "created_at": "...", "last_active_at": "..."},
    {"id": "session-2", "title": "你叫张三", "created_at": "...", "last_active_at": "..."}
  ]
}
```

## demo 在做什么

`demo_sessions.py` 演示 4 件事：

1. **新建** 3 个 session，每个写不同内容
2. **切换**回 session-1，验证读到 session-1 自己的历史
3. **删除** session-2 → checkpoint 也被 purge
4. **持久化** —— 关掉所有连接，再开新 saver，sessions.json + leader.db 都还在

## 跑

```bash
python learn/05-memory-persistence/03-thread-id-and-sessions/demo_sessions.py
```

预期输出：

```
=== 新建 3 个 session 并各写一条 ===
  session-1: 张三
  session-2: 李四
  session-3: 王五

=== 切换回 session-1 验证隔离 ===
  当前 session: session-1
  当前 thread_id 的历史: ['张三']  ← 只看得到自己

=== 删除 session-2（联动 purge）===
  删除前: ['session-1', 'session-2', 'session-3']
  删除后: ['session-1', 'session-3']
  leader.db 中的 thread_id: ['session-1', 'session-3']  ← session-2 的 checkpoint 也没了

=== 跨"进程"重开，状态恢复 ===
  sessions: ['session-1', 'session-3']  ✓
  current : session-1                   ✓
```

## 在项目里的位置

- `src/persistence/session_manager.py::SessionManager` —— 元数据 CRUD
- `src/interface/cli.py::_handle_command` —— `/new` `/sessions` `/switch` `/delete` `/title` 命令路由
