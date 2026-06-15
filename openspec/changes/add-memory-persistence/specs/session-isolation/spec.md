## ADDED Requirements

### Requirement: 三级隔离粒度

系统 SHALL 把会话状态按 `user_id` → `conversation_id` → `plan_run_id` 三级隔离：用户记忆作用于 user 级、会话记忆作用于 conversation 级、共享黑板与 LangGraph state 作用于 plan_run 级；任何跨级访问必须显式经过对应 Store 的 API。

#### Scenario: plan_run 不污染会话

- **WHEN** plan_run 结束（30 分钟后或显式 expire）
- **THEN** Redis 中 `run:{rid}:*` 全部被删
- **AND** 同一 conversation 后续 plan_run 读不到旧黑板

### Requirement: Key 命名规范

系统 SHALL 强制使用以下 key 模式：
- `mem:user:{user_id}:profile`
- `mem:conv:{conv_id}:history`
- `mem:conv:{conv_id}:summary`
- `mem:conv:{conv_id}:meta`
- `run:{plan_run_id}:blackboard`
- `run:{plan_run_id}:state`
所有 Store 内部生成 key 的逻辑集中在一个工具函数 `make_key(kind, **ids)`，禁止业务直接拼字符串。

#### Scenario: 工具函数验证

- **WHEN** 调 `make_key("conv_history", conv_id="c1")`
- **THEN** 返回 `"mem:conv:c1:history"`

#### Scenario: 非法 kind

- **WHEN** 调 `make_key("xxx", ...)`
- **THEN** 抛 `ValueError` 列出合法 kind

### Requirement: TraceContext 集成

系统 SHALL 让 `TraceContext`（来自 `add-chatbi-foundation`）在每次 plan_run 开始时由中控更新 `plan_run_id`，并保证所有 Store 的读写 span 都带上完整三元组 `user_id` / `conv_id` / `plan_run_id`。

#### Scenario: span metadata 完整

- **WHEN** plan_run 内 Store.set 被调用
- **THEN** 对应 LangSmith span metadata 含三元组（缺失时为空字符串）
