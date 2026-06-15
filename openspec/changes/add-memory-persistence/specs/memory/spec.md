## ADDED Requirements

### Requirement: 用户记忆存储

系统 SHALL 提供 `UserMemoryStore`，支持 `get(user_id) -> UserProfile | None`、`set(user_id, profile)`、`upsert(user_id, **fields)`、`delete(user_id)`，数据以 JSON 格式存储于 Key `chatbi:mem:user:{user_id}:profile`，永久不过期。

#### Scenario: upsert 合并字段

- **WHEN** 已有 profile `{lang:"zh"}`，调用 `upsert(uid, region="华南")`
- **THEN** profile 变为 `{lang:"zh", region:"华南"}`
- **AND** Redis 中对应 key 内容更新

#### Scenario: 永久不过期

- **WHEN** 设置 profile 超过 7 天后再读
- **THEN** 仍能读到（即未因 TTL 删除）

### Requirement: 会话记忆存储

系统 SHALL 提供 `SessionMemoryStore`，支持 `append_message(conv_id, msg)`、`get_history(conv_id, limit=None)`、`get_summary(conv_id)`、`set_summary(conv_id, summary)`、`clear(conv_id)`；TTL 默认 7 天，可通过 Settings 配置。

#### Scenario: append 持久化

- **WHEN** 连续 append 3 条 message
- **THEN** `get_history(conv_id)` 返回长度为 3 的列表
- **AND** Redis 与 SQLite 都含对应记录

#### Scenario: TTL 生效

- **WHEN** TTL 配置为 1 秒，写入后等待 2 秒
- **THEN** Redis 中已被清；SQLite reaper 后续清理

### Requirement: 共享黑板

系统 SHALL 提供 `BlackboardStore`，支持 `set(plan_run_id, key, value)`、`get(plan_run_id, key)`、`dict_view(plan_run_id) -> dict`、`expire(plan_run_id)`；TTL 默认 30 分钟。

#### Scenario: 多 Teammate 共享

- **WHEN** Teammate A 写 `set(rid, "df", df_json)`，Teammate B 在同一 plan_run 读 `get(rid, "df")`
- **THEN** B 拿到 `df_json`

#### Scenario: 不同 plan_run 隔离

- **WHEN** plan_run X 写 `key1`，plan_run Y 读 `key1`
- **THEN** Y 拿到 None

### Requirement: 上下文压缩

系统 SHALL 在 `SessionMemoryStore.append_message` 后，当 `len(history) > settings.compression_threshold`（默认 30）时异步触发 `Compressor.compress(history) -> summary` 并写入 summary key，同时把 history 截断为最近 `settings.compression_keep_tail`（默认 10）条；旧 history 归档到 SQLite `conversation_archive` 表。

#### Scenario: 触发压缩

- **WHEN** 第 31 条 message append
- **THEN** 异步任务被调度
- **AND** 完成后 `get_summary(cid)` 非空且 `get_history(cid)` 长度为 10

#### Scenario: 归档存在

- **WHEN** 触发压缩后查询 `conversation_archive`
- **THEN** 至少有一条对应该 conv_id 的归档记录
