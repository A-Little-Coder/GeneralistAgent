## Context

中控 Agent 要支撑多用户、多会话、多轮对话，并支持 plan_run 内多 Teammate 共享中间结果。需要一套清晰的会话隔离粒度（user → conversation → plan_run）和明确的记忆类型（用户偏好长期 vs 对话内容会话）。持久化必须高可用：Redis 故障时降级到本地 SQLite，业务不感知。本 change 的目标是把这套抽象一次性固化下来，避免之后每个 change 各自实现一份记忆/状态。

## Goals / Non-Goals

**Goals:**
- 三级隔离模型 + Key 命名规范
- 用户记忆 / 会话记忆 / 共享黑板 三套抽象
- Redis 热 + 本地 SQLite 冷 双层后端，自动降级与异步回写
- 接入 deepagents 上下文压缩
- LangSmith 埋点（每次读 / 写 / 降级都打 span）
- 提供调试 CLI

**Non-Goals:**
- 不实现 SSE / 续跑（在 `add-streaming-conversation`）
- 不实现规划 / 黑板内容写入（仅提供存储原语，写入由各 Teammate / 规划层完成）
- 不做跨进程缓存一致性（中控暂时单实例 / 单进程内一致即可）

## Decisions

### 决策 1：三级隔离粒度

```
user_id ─ conversation_id ─ plan_run_id
   │            │                │
   │            │                └─ 一次规划+执行；多 Teammate 共享黑板范围
   │            └─ 一次完整对话（多轮）；会话记忆作用范围
   └─ 跨对话；用户记忆作用范围
```

- `plan_run_id` 在每次中控开始一次规划时由 `uuid4` 生成
- `conversation_id` 由会话层从前端传入或新建
- `user_id` 由会话层从认证态传入

### 决策 2：Key 命名

```
mem:user:{user_id}:profile          # 用户记忆，永久
mem:conv:{conv_id}:history          # 会话记忆（对话历史 list），TTL 7d
mem:conv:{conv_id}:summary          # deepagents 压缩产物，TTL 7d
mem:conv:{conv_id}:meta             # 会话级元数据（创建时间、用户偏好快照），TTL 7d
run:{plan_run_id}:blackboard        # 黑板（dict），TTL 30min
run:{plan_run_id}:state             # LangGraph checkpoint，TTL 30min
```

- 所有 key 含 namespace 前缀 `chatbi:`，避免与其他业务冲突
- TTL 在 Settings 中可配（避免硬编码）

### 决策 3：抽象层

```
chatbi/infra/memory/
├── types.py           # UserProfile / ConversationHistory / Blackboard pydantic 模型
├── user_memory.py     # UserMemoryStore.get/set/upsert/delete
├── session_memory.py  # SessionMemoryStore.append_message/get_history/get_summary/set_summary
├── blackboard.py      # BlackboardStore.set/get/dict_view/expire
└── compression.py     # 调 deepagents 压缩

chatbi/infra/persistence/
├── backend.py         # MemoryBackend 抽象基类
├── redis_backend.py   # RedisBackend
├── sqlite_backend.py  # SQLiteBackend
├── fallback.py        # FallbackBackend(redis, sqlite)
└── codec.py           # 序列化/反序列化 (json/msgpack)
```

- `MemoryBackend` 暴露 `get/set/delete/incr/expire/keys_with_prefix`
- 各 Store 只面向后端抽象操作，不关心是 Redis 还是 SQLite

### 决策 4：双层存储与降级

```
读：
  RedisBackend.get(key)
   ├── ok → 返回
   └── error / timeout(2s) →
        SQLiteBackend.get(key)
         ├── ok → 返回 + 记录"降级读"事件
         └── miss → None

写：
  尝试同时写 Redis + SQLite（双写）
   ├── Redis ok + SQLite ok → 成功
   ├── Redis ok + SQLite fail → 记 WARN，仍成功（Redis 是热）
   ├── Redis fail + SQLite ok → 进入"降级模式"，后续 60s 内全走 SQLite，并触发心跳重试 Redis
   └── Redis fail + SQLite fail → 抛 PersistenceError
```

- 降级模式记录在内存标志位 `_redis_degraded_until: float`；超过到期时间或心跳成功后清除
- 恢复时异步回写：从 SQLite 把 TTL 未到期的关键 key 回写 Redis（队列 + 限流）

### 决策 5：序列化

- 默认 JSON（人类可读，便于 SQLite 调试）
- 用户记忆 / 会话记忆 / 黑板都用 pydantic 模型 `model_dump_json()`
- 大对象（如完整 LangGraph state）压缩 + base64

### 决策 6：deepagents 上下文压缩集成

- `SessionMemoryStore.append_message` 后，若 `len(history) > threshold`（默认 30 条），异步触发压缩
- 压缩调 deepagents 提供的能力（查 `deepagents.compression` 或等价接口；如版本无此能力，临时退化为 LangChain `ConversationSummaryMemory`）
- 压缩结果写入 `mem:conv:{cid}:summary`，并把 `history` 截断为最近 N 条
- 压缩前后版本都保留：旧 history 写入 SQLite `conversation_archive` 表

### 决策 7：调试 CLI

- `chatbi memory dump --user <uid>` → JSON 输出全部用户偏好
- `chatbi memory dump --conv <cid>` → 输出对话历史 + 摘要
- `chatbi memory dump --run <rid>` → 输出黑板 + state
- `chatbi memory clear --conv <cid>` → 清除会话记忆（需 `--yes` 确认）

### 决策 8：SQLite schema

```sql
CREATE TABLE kv (
  key TEXT PRIMARY KEY,
  value BLOB,
  expires_at INTEGER,        -- unix ts，NULL 表示永久
  updated_at INTEGER
);
CREATE INDEX idx_kv_expires ON kv(expires_at);

CREATE TABLE conversation_archive (
  conv_id TEXT,
  archived_at INTEGER,
  history_json TEXT,
  PRIMARY KEY (conv_id, archived_at)
);
```

- 后台 reaper 协程每 5 分钟清 `expires_at < now()` 的行
- 文件路径默认 `~/.chatbi/chatbi.sqlite`，可通过 `SQLITE_PATH` 覆盖

## Risks / Trade-offs

- [Risk] 双写下 Redis 与 SQLite 数据漂移 → Mitigation：所有写操作以"成功条件 = Redis ok"为准；SQLite 仅作冷备；降级期间 Redis 恢复后异步回写
- [Risk] SQLite 高并发写性能差 → Mitigation：用 `aiosqlite` + `journal_mode=WAL`；中控单进程下并发写量不大，可接受
- [Risk] deepagents 压缩接口尚未确定 → Mitigation：`compression.py` 中先包一层 `Compressor` 抽象，提供 `DeepAgentsCompressor` 与 `LangChainSummaryCompressor` 两种实现，按版本探测自动选择
- [Trade-off] TTL 全局而非 per-key 可配 → 简化设计；后续如需精细控制可在 Settings 加分类 TTL

## Migration Plan

- 新建项目，无迁移
- 后续若需多进程/多机部署，把 SQLite 后端替换为共享 DB（PostgreSQL）；接口不变

## Open Questions

- 用户记忆是否要做 schema 校验（必须哪些字段）？暂定 free-form dict，由各业务模块自约束
- 黑板是否需要 ACL（Teammate A 不能读 B 写的 key）？暂不做，plan_run 内默认互信
