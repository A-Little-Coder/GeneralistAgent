## 1. 类型与命名

- [ ] 1.1 在 `chatbi/infra/memory/types.py` 定义 `UserProfile` / `Message` / `ConversationHistory` / `Blackboard` pydantic 模型
- [ ] 1.2 在 `chatbi/infra/persistence/keys.py` 实现 `make_key(kind, **ids)`；含全部 6 种 kind 与非法报错
- [ ] 1.3 单元测试：所有 kind 的拼装 + 非法 kind

## 2. 后端抽象与 Redis 实现

- [ ] 2.1 实现 `chatbi/infra/persistence/backend.py::MemoryBackend` 抽象基类
- [ ] 2.2 实现 `chatbi/infra/persistence/redis_backend.py::RedisBackend`：基于 `redis.asyncio.Redis`，2s 超时，namespace 前缀
- [ ] 2.3 单元测试：用 `fakeredis.aioredis` 跑 set/get/delete/incr/expire

## 3. SQLite 实现 + reaper

- [ ] 3.1 实现 `chatbi/infra/persistence/sqlite_backend.py::SQLiteBackend`：基于 `aiosqlite`，启动时建表，启用 WAL
- [ ] 3.2 启动 reaper 协程（asyncio task），每 5 分钟清过期行
- [ ] 3.3 实现 `keys_with_prefix` 用 `LIKE` 查询
- [ ] 3.4 单元测试：set→get→TTL 过期→reaper 清理

## 4. FallbackBackend

- [ ] 4.1 实现 `chatbi/infra/persistence/fallback.py::FallbackBackend`
- [ ] 4.2 降级标志位、心跳探测协程、限流回写队列
- [ ] 4.3 LangSmith span 标 `persistence_degrade / recover / partial_write`
- [ ] 4.4 单元测试：mock Redis 抛错，验证降级与恢复

## 5. 序列化

- [ ] 5.1 实现 `chatbi/infra/persistence/codec.py::dumps/loads`（JSON）
- [ ] 5.2 大对象（>1MB）触发 zstd 压缩 + base64 包装
- [ ] 5.3 单元测试：往返、超大对象、非法字节

## 6. UserMemoryStore

- [ ] 6.1 实现 `chatbi/infra/memory/user_memory.py::UserMemoryStore`
- [ ] 6.2 单元测试：get/set/upsert/delete + 永久不过期

## 7. SessionMemoryStore + 压缩

- [ ] 7.1 实现 `chatbi/infra/memory/session_memory.py::SessionMemoryStore`
- [ ] 7.2 实现 `chatbi/infra/memory/compression.py::Compressor` 抽象 + `DeepAgentsCompressor` + `LangChainSummaryCompressor`
- [ ] 7.3 启动期探测 deepagents 压缩接口可用性，自动选择实现
- [ ] 7.4 触发条件：append 后 `len(history) > threshold` 异步压缩
- [ ] 7.5 归档到 `conversation_archive` 表
- [ ] 7.6 单元测试：阈值触发、归档落库、压缩失败回退

## 8. BlackboardStore

- [ ] 8.1 实现 `chatbi/infra/memory/blackboard.py::BlackboardStore`
- [ ] 8.2 单元测试：set/get、不同 plan_run 隔离、TTL 自动过期

## 9. CLI

- [ ] 9.1 实现 `chatbi memory dump --user/--conv/--run`
- [ ] 9.2 实现 `chatbi memory clear --conv <cid> --yes`
- [ ] 9.3 README 文档与示例

## 10. 集成与验收

- [ ] 10.1 集成测试：完整流程 user_memory + session_memory + blackboard
- [ ] 10.2 集成测试：Redis 故障切换 SQLite，再恢复回写
- [ ] 10.3 LangSmith trace 中可看到读写 span 与降级事件
- [ ] 10.4 README 增加章节：《记忆与持久化》《Key 命名规范》
