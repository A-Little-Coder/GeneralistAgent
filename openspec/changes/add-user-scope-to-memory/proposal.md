## Why

当前 `add-memory-persistence` 落地的多 session 模型是**单用户模型**：`memory/sessions.json` 没有用户维度，`leader.db` 的 `thread_id` 就是 `session-1` / `session-2`。多个使用者（不同员工、未来的 API 客户端）共用同一台机器或同一进程时会**串台**——alice 看得到 bob 的对话，session_id 也会撞名。

为后续 API 化（每个请求带 user_id）铺路，先在 CLI 阶段把 user_id 这层模型补齐：sessions 按 user 分组、`thread_id` 拼 `user:session`、Teammate 维度不动（每轮焚毁，天然不串）。

## What Changes

- **CLI 启动时输入 user_id**：`python src/main.py` 启动后先 `input("请输入 user_id (回车默认 default): ")`，绑定本会话身份。
- **运行中切换 user**：新增 `/user <user_id>` 命令，重新加载该 user 的 sessions、提示符前缀变更。
- **sessions.json 改结构**：顶层 `users` 字段，按 user_id 分组；每 user 独立的 `current` + `sessions` 列表。
- **leader.db thread_id 拼 user_id**：所有进入 `astream` / `purge` 的 thread_id 都从 `"session-X"` 改为 `"{user_id}:session-X"`。
- **旧数据迁移（启动时一次性）**：
  - 旧 `sessions.json`（无 `users` 字段）→ 全部归到 `users.default`
  - 旧 `leader.db` 中不含 `:` 的 `thread_id` → 改名为 `default:<原id>`
  - 迁移幂等；迁完写回磁盘
- **CLI banner / 提示符**：显示 `user/session`，让用户清楚自己是谁。
- **session_id 跨 user 允许同名**：alice 的 `session-1` 与 bob 的 `session-1` 互不可见。
- **teammate_id 不变**：Teammate 每轮焚毁，无串台风险，不加 user 前缀。

## Capabilities

### New Capabilities

- `user-scope`: user_id 维度的引入、CLI 输入与切换、旧数据自动迁移。

### Modified Capabilities

- `session-management`: sessions.json 顶层改为 `users` 分组；所有 CRUD 操作绑定当前 user 上下文；session_id 唯一性放宽到 user 内。
- `leader-persistence`: `thread_id` 由 `session_id` 升级为 `"{user_id}:{session_id}"`；`purge` 接受复合 thread_id；新增旧数据迁移 Requirement。

## Impact

- **新增模块**：`src/persistence/user_migration.py`（一次性迁移辅助函数）。
- **修改模块**：
  - `src/persistence/session_manager.py`：内部数据结构 + 全部公共方法签名加 user_id 上下文（或 SessionManager 改为持有 current_user_id 的有状态对象）
  - `src/persistence/leader_store.py`：新增 `migrate_legacy_thread_ids()` 助手
  - `src/interface/cli.py`：启动输入 user_id、`/user` 命令、提示符 / banner 改造
- **测试新增**：`tests/test_user_scope.py`（user 隔离 / 迁移 / 命令切换）；现有 `tests/test_session_manager.py` 部分用例改造为 user 版本。
- **行为变更**：
  - 没有指定 user_id 时默认 `default`，行为与改造前的"单用户"等价
  - CLI 首次启动比之前多一行输入
  - sessions.json 文件格式不向前兼容（一次性迁移）
- **教学产出**：`learn/05-memory-persistence/` 不改（user_id 是项目级便利，不属于 LangGraph 核心概念）。
- **不影响**：Teammate / Runner / TeamManager / 编排工具集，全部保持 add-memory-persistence 时的状态。
