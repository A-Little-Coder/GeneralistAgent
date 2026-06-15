## Why

中控 Agent 要支撑多用户、多会话、多轮对话，并支持多 Agent 之间在一次规划运行中共享中间结果。这要求清晰的会话隔离粒度（user / conversation / plan_run）和明确的记忆类型（用户偏好长期记忆 vs 对话内容会话记忆）。同时持久化必须高可用：Redis 故障时降级到本地 SQLite，不能让用户感知。本 change 把这套"记忆 + 持久化 + 会话隔离"一次性固化。

## What Changes

- 定义三级隔离模型：`user_id`（跨对话）→ `conversation_id`（多轮）→ `plan_run_id`（单次规划-执行；多 Agent 共享黑板的范围）
- 定义两类记忆：
  - 用户记忆（`user_memory`）：偏好等长期事实，永久存储
  - 会话记忆（`session_memory`）：对话历史 + deepagents 压缩产物，TTL 7 天
- 定义共享黑板（`blackboard`）：plan_run 级，TTL 30 分钟，结束即可清
- 统一 Key 命名约定：`mem:user:{uid}:profile`、`mem:conv:{cid}:history`、`mem:conv:{cid}:summary`、`run:{rid}:blackboard`、`run:{rid}:state`
- 实现两层存储：Redis 热（默认）+ 本地 SQLite 冷（降级 / 兜底）
- 实现存储后端抽象 `MemoryBackend`：`RedisBackend`、`SQLiteBackend`、`FallbackBackend`（Redis 不可用自动切 SQLite，恢复后异步回写）
- 集成 deepagents 上下文压缩：会话记忆超过阈值后调用 deepagents 压缩，压缩前后版本都存
- 提供记忆读写的 LangSmith 埋点（每次读 / 写 / 降级都打 span）
- 提供 CLI 工具：`chatbi memory dump --user xxx` / `--conv xxx`，便于调试与人工巡检

## Capabilities

### New Capabilities

- `memory`: 用户记忆 + 会话记忆 + 共享黑板的统一抽象
- `persistence`: Redis / SQLite 双层存储与降级策略
- `session-isolation`: 三级隔离与 Key 命名约定

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/infra/memory/`、`chatbi/infra/persistence/`
- 影响依赖：新增 `redis`、`aiosqlite` 或 `sqlalchemy`
- 影响配置：`.env` 新增 `REDIS_URL`、`SQLITE_PATH`、`MEMORY_TTL_*`
- 依赖前置：`add-chatbi-foundation`
- 被依赖：`add-orchestrator-planner`（黑板）、`add-streaming-conversation`（恢复 plan_run 状态）
