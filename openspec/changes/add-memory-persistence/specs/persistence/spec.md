## ADDED Requirements

### Requirement: MemoryBackend 抽象

系统 SHALL 在 `chatbi.infra.persistence.backend` 定义 `MemoryBackend` 抽象基类，方法 `async get(key) -> bytes | None`、`async set(key, value, ttl_s=None)`、`async delete(key)`、`async expire(key, ttl_s)`、`async incr(key, by=1)`、`async keys_with_prefix(prefix) -> list[str]`，并提供 `RedisBackend`、`SQLiteBackend` 两个实现。

#### Scenario: Redis 与 SQLite 行为一致

- **WHEN** 对 RedisBackend 与 SQLiteBackend 分别执行 set→get→delete 序列
- **THEN** 两端可观察的对外结果一致（拿到值、拿到 None）

### Requirement: SQLite schema 与 reaper

系统 SHALL 在首次启动时初始化 SQLite 表 `kv(key TEXT PRIMARY KEY, value BLOB, expires_at INTEGER NULL, updated_at INTEGER)` 与 `conversation_archive`；并启动后台 reaper 协程，每 5 分钟删除 `expires_at IS NOT NULL AND expires_at < now()` 的行；启用 WAL 模式。

#### Scenario: reaper 清理过期

- **WHEN** 写入 ttl=1s 的 key 后等 6 分钟
- **THEN** SQLite 中该 row 已被删除

### Requirement: FallbackBackend 降级

系统 SHALL 提供 `FallbackBackend(redis, sqlite)`，行为：
- 读：先 Redis（2s 超时），失败 / miss 时回落 SQLite；
- 写：双写 Redis + SQLite；Redis 失败时进入"降级模式"（默认 60 秒），降级期间读写都直接走 SQLite；
- 降级期间每 10 秒心跳探测 Redis，恢复后退出降级并异步回写未过期 key。

每次降级 / 恢复 / 双写不一致都需要在 LangSmith span 上打 `event=persistence_degrade / persistence_recover / persistence_partial_write`。

#### Scenario: Redis 故障读

- **WHEN** Redis 客户端 `get` 抛超时
- **THEN** FallbackBackend 自动调 SQLite 的 `get` 并返回结果
- **AND** 标志位 `_redis_degraded_until` 被设为 now+60s

#### Scenario: 恢复回写

- **WHEN** 降级期间写入 5 个 key，10 秒后 Redis 恢复
- **THEN** 异步任务把 5 个 key 回写到 Redis（受限流控制）
- **AND** LangSmith 中出现 `persistence_recover` 事件

### Requirement: 序列化与命名空间

系统 SHALL 在 `chatbi.infra.persistence.codec` 提供 `dumps(obj) -> bytes` / `loads(b) -> obj`（默认 JSON），并强制所有 key 加 `chatbi:` 前缀；Settings 中可配置前缀以隔离环境（如 `chatbi-staging:`）。

#### Scenario: 前缀生效

- **WHEN** Settings 设 `key_namespace=chatbi-staging`，业务调用 `set("mem:user:1:profile", ...)`
- **THEN** 实际 Redis key 为 `chatbi-staging:mem:user:1:profile`

### Requirement: 调试 CLI

系统 SHALL 提供 `chatbi memory dump` 子命令，参数 `--user`、`--conv`、`--run` 三选一，输出对应记忆的 JSON 表示；`chatbi memory clear --conv <cid> --yes` 删除会话记忆。

#### Scenario: dump conv

- **WHEN** 执行 `chatbi memory dump --conv c1`
- **THEN** stdout 输出 `{"history":[...], "summary":"...", "meta":{...}}`
