## MODIFIED Requirements

### Requirement: Leader 跨进程对话历史持久化
Leader 的对话历史 SHALL 通过 `AsyncSqliteSaver` 持久化到 `memory/leader.db`，以 `"{user_id}:{session_id}"` 作为 LangGraph `thread_id`，进程重启后能恢复任意 (user, session) 组合的完整历史。

#### Scenario: 写入并恢复历史
- **WHEN** 用户以 user=alice 在 session-A 中说"我叫张三"后退出 CLI，再次启动以 user=alice 并 `/switch A`
- **THEN** Leader 询问"我叫什么名字" SHALL 回答"张三"

#### Scenario: 不同 user 历史隔离
- **WHEN** alice 在 session-1 说"我叫张三"，bob 也在 session-1 说"我叫李四"
- **THEN** alice 询问名字时 SHALL 回答张三、bob 询问时 SHALL 回答李四，互不可见

#### Scenario: 首次启动无历史
- **WHEN** 进程启动且 `memory/leader.db` 不存在
- **THEN** `LeaderStore` SHALL 自动创建数据库与表结构，不抛异常

### Requirement: CLI 入参不再传完整 state
`agent.astream` 调用 SHALL 仅传递本轮新消息（`{"messages": [HumanMessage(user_input)]}`），不再手动 rebuild 完整历史；历史由 `AsyncSqliteSaver` 按 `thread_id = "{user_id}:{session_id}"` 自动加载。

#### Scenario: 流式后无需 rebuild
- **WHEN** 一轮流式完成
- **THEN** CLI SHALL **不**调用 `rebuild_state`、SHALL **不**累积 messages 列表，由 checkpointer 自动落盘

#### Scenario: 多轮上下文连续
- **WHEN** 用户在同一 (user, session) 连续多轮提问
- **THEN** 每轮 Leader SHALL 能基于 AsyncSqliteSaver 加载的历史回答

### Requirement: 工具返回入库截断
进入 Leader 视角的工具返回（编排工具的 dict 中长文本字段）SHALL 在工具实现层调用 `truncate_for_persist`，超过 `TOOL_PERSIST_MAX_CHARS`（默认 4000 字符）的字段尾部附加 `…[已截断，原文 N 字符]`。

#### Scenario: 短返回不截断
- **WHEN** 工具返回字段长度 ≤ 阈值
- **THEN** 返回值 SHALL 原样保留

#### Scenario: 长返回被截断
- **WHEN** 工具返回字段长度 > 阈值
- **THEN** 返回值 SHALL 被截断并附注脚 `…[已截断，原文 N 字符]`

#### Scenario: 阈值可配置
- **WHEN** 环境变量 `TOOL_PERSIST_MAX_CHARS` 被设置为整数
- **THEN** `truncate_for_persist` SHALL 使用该值代替默认 4000

### Requirement: 持久化文件路径
`memory/leader.db` 和 `memory/sessions.json` SHALL 位于项目根目录的 `memory/` 子目录；该目录不存在时自动创建；`memory/` SHALL 被加入 `.gitignore`。

#### Scenario: 自动建目录
- **WHEN** `LeaderStore` 初始化时 `memory/` 不存在
- **THEN** SHALL 创建该目录并继续初始化

#### Scenario: gitignore 排除
- **WHEN** 在干净 git 工作区运行一轮对话产生 leader.db
- **THEN** `git status` SHALL **不**显示 `memory/leader.db` 为未跟踪文件

## ADDED Requirements

### Requirement: leader.db 旧 thread_id 迁移
`LeaderStore.setup()` SHALL 在建表之后执行一次幂等迁移：将 `checkpoints` 与 `writes` 表中所有不含 `:` 的 `thread_id` 改为 `default:<原值>`。

#### Scenario: 旧数据迁移
- **WHEN** leader.db 中存在 `thread_id = 'session-1'` 的行
- **THEN** 启动后该行 thread_id SHALL 为 `default:session-1`

#### Scenario: 迁移幂等
- **WHEN** 库中已无任何不含 `:` 的 thread_id
- **THEN** 迁移 SHALL 不修改任何行

#### Scenario: 事务保护
- **WHEN** 迁移 SQL 执行中失败
- **THEN** 事务 SHALL 回滚，磁盘状态等于迁移前
