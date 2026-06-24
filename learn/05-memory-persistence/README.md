# learn/05-memory-persistence —— 双层记忆持久化

> 配套 openspec change `add-memory-persistence`（已归档时改成 `archive/2026-MM-DD-...`）。
> 本目录的所有 demo 都是**独立可运行**的最小例子，不 import `src/`，方便脱离项目跑通核心概念后再回头读项目代码。

## 解决了什么问题

GeneralistAgent 之前的"记忆"非常脆弱：

```
┌────────────────────────────────────────────────────────────┐
│ Leader  : CLI 退出 → 完全失忆（rebuild_state 只在进程内有效）│
│ Teammate: 每次唤起 → 完全失忆（每 turn 都重建 Agent）        │
└────────────────────────────────────────────────────────────┘
```

升级后：

```
┌─────────────────────────────────────────────────────────────────┐
│ Leader   : SqliteSaver → memory/leader.db                       │
│            • 跨进程恢复（重启 CLI 历史还在）                      │
│            • 多 session 切换（类豆包 /new）                       │
│                                                                 │
│ Teammate : MemorySaver（per Runner，RAM only）                   │
│            • 一个用户请求内多次唤起共享记忆（X2）                 │
│            • 请求结束 cleanup_spawned_in_turn 焚毁                │
│            • 不写盘、不污染 leader.db                             │
└─────────────────────────────────────────────────────────────────┘
```

## 双层记忆边界图

```
                  ┌──────────────  磁盘  ──────────────┐
                  │   memory/                          │
                  │   ├── leader.db   (SqliteSaver)    │
                  │   └── sessions.json (SessionManager)│
                  └────────────────────────────────────┘
                              ▲
                              │ Leader 长期持久
                              │
   ┌──────────────────────────┴──────────────────────────────────┐
   │                       CLI REPL                              │
   │                                                             │
   │   build_agent(checkpointer=SqliteSaver, thread_id=sess_id)  │
   │                          │                                  │
   │                          │ spawn_teammate                   │
   │                          ▼                                  │
   │   ┌─────────────────────────────────────────────────────┐   │
   │   │  Teammate A (Runner)                                │   │
   │   │    build_agent(checkpointer=MemorySaver())          │   │
   │   │    thread_id = teammate_id                          │   │
   │   │    ──── 一个请求内：累积 ────                       │   │
   │   │    ──── 请求结束：cleanup → 焚 ────                  │   │
   │   └─────────────────────────────────────────────────────┘   │
   └─────────────────────────────────────────────────────────────┘
```

## 阅读顺序

| 章节 | 主题 | 关键概念 |
|---|---|---|
| 01-memory-saver       | RAM 内的最小持久化       | `MemorySaver` / `thread_id` |
| 02-sqlite-saver       | 落盘 + 跨进程恢复        | `SqliteSaver.from_conn_string` |
| 03-thread-id-sessions | 多 session 隔离          | 同库不同 thread_id |
| 04-teammate-vs-leader | 双层记忆边界示意         | 两种 saver 并存 |
| 05-cleanup-lifecycle  | Teammate 创建 / 唤起 / 焚毁 | asyncio.Task 收尾 |

## 怎么跑

每个 demo 都是：

```bash
cd D:/CodeProjects/PycharmProjects/GeneralistAgent
python learn/05-memory-persistence/01-memory-saver/demo_memory_saver.py
```

需要的依赖（项目已装）：

```
langgraph
langgraph-checkpoint
langgraph-checkpoint-sqlite
langchain-core
```

不需要 API Key —— demo 用 `GenericFakeChatModel` 或最简 graph，离线就能跑。

## 与项目代码的对照

| 教学概念              | 项目对应                                                    |
|---|---|
| `MemorySaver`         | `src/orchestration/runner.py::Runner._memory_saver`         |
| `SqliteSaver`         | `src/persistence/leader_store.py::LeaderStore`              |
| `thread_id` 多 session | `src/persistence/session_manager.py::SessionManager`        |
| 工具截断              | `src/persistence/tool_truncate.py::truncate_for_persist`    |
| 焚毁                  | `src/orchestration/team.py::TeamManager.cleanup_spawned_in_turn` |

读完本目录后，再回到上述项目文件就能秒懂改动逻辑。
