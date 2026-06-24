## Why

当前 GeneralistAgent 的 Leader 仅在单个 CLI 进程内通过手动 `rebuild_state` 拼接历史，重启即丢失；Teammate 则每次被唤起都用全新 `MemorySaver` 重建 Agent，导致同一请求内多次 `assign_task / send_message` 之间彻底失忆，Leader 必须每次重发完整上下文，浪费 token 又难调试。需要一套清晰的双层记忆方案：Leader 长期持久（类似豆包多会话），Teammate 短期共享（请求内累积、turn 结束焚毁）。

## What Changes

- **新增 Leader 持久化层**：用 LangGraph 官方 `SqliteSaver` 取代 `MemorySaver`，存储于根目录 `memory/leader.db`，按 `thread_id = session_id` 跨进程恢复历史。
- **新增 Session 管理**：引入 `SessionManager`，元数据存于 `memory/sessions.json`；标题取用户首条消息前 20 字；CLI 新增 `/new`、`/sessions`、`/switch`、`/delete`、`/title` 命令；首启无历史时自动建 `session-1`。
- **改造 Teammate 记忆模型（X2）**：Runner 启动时一次性 `build_agent` 并持有 `MemorySaver`，本请求内多次唤起共享记忆；turn 结束统一焚毁（cleanup_spawned_in_turn）。
- **删除 Leader 手动 rebuild_state**：依赖 SqliteSaver 自动加载/落盘，`agent.astream` 每次只传新消息（`messages=[HumanMessage(...)]`）。
- **ToolMessage 持久化截断**：超过 `_TOOL_MESSAGE_PERSIST_MAX = 4000` 字符的工具返回在写入 SqliteSaver 前尾部追加截断注脚；当 turn 推理使用原文不受影响。
- **解除 Leader 单 Teammate 约束**：删除 `_SYSTEM_PROMPT` 中 "一个查询请求只需要建一个 Teammate" 一句。
- **`/delete <session>` 同步清 checkpoint**：直接对 `leader.db` 执行 `DELETE FROM checkpoints/writes WHERE thread_id=?`，避免历史残留。
- **build_agent 参数化 checkpointer**：移除硬编码 `MemorySaver()`，由调用方注入。
- **教学产出**：开发完成后，在根目录 `learn/05-memory-persistence/` 输出 5 个可运行 demo + 中文说明文档。

## Capabilities

### New Capabilities

- `leader-persistence`: Leader 跨进程对话历史持久化（SqliteSaver + session_id 作为 thread_id）。
- `session-management`: 多会话切换与元数据维护（创建 / 列出 / 切换 / 删除 / 改标题）。
- `teammate-runtime-memory`: Teammate 在一次用户请求内的累积记忆（X2 语义）与 turn 结束焚毁。

### Modified Capabilities

- `streaming-output`: 删除"流式后手动重建对话状态"Requirement 的 rebuild 行为，改为依赖 checkpointer 自动管理；CLI 入参从全量 state 改为单条新消息。
- `agent-team-orchestration`: spawn_teammate 后 Teammate 在请求内持有累积记忆；新增"请求结束焚毁本轮新建 Teammate"行为；Leader 不再受"每请求一个 Teammate"约束。

## Impact

- **新增模块**：`src/persistence/leader_store.py`、`src/persistence/session_manager.py`。
- **修改模块**：`src/core/agent.py`（checkpointer 入参化）、`src/interface/cli.py`（注入 SqliteSaver、删除 rebuild_state、新增 session 命令）、`src/orchestration/runner.py`（构建一次 + 累积记忆）、`src/orchestration/team.py`(新增 `cleanup_spawned_in_turn`)。
- **新增依赖**：`langgraph-checkpoint-sqlite`（清华源安装）。
- **新增运行时目录**：根目录 `memory/`（含 `leader.db`、`sessions.json`），加入 `.gitignore`。
- **测试新增**：`tests/test_leader_persistence.py`、`tests/test_session_manager.py`、`tests/test_teammate_memory.py`、`tests/test_cleanup_turn.py`。
- **行为变更**：Teammate 不再热更新 SKILL（spawn 时载入，请求内冻结）；Leader 仍保留 SKILL 热更新能力。
- **教学新增**：`learn/05-memory-persistence/` 目录及配套 demo。
