## ADDED Requirements

### Requirement: CLI 启动绑定 user_id
CLI 启动 SHALL 在打印 banner 后通过 `input()` 提示用户输入 user_id；回车视为 `default`；包含冒号 `:` 的输入 SHALL 被拒绝并要求重输。

#### Scenario: 输入有效 user_id
- **WHEN** 用户启动 CLI 并输入 "alice"
- **THEN** 系统 SHALL 把 `alice` 设为当前 user_id，所有后续 session 操作落在该 user 上下文

#### Scenario: 回车使用默认
- **WHEN** 用户在 user_id 提示处直接回车
- **THEN** 当前 user_id SHALL 设为 `default`

#### Scenario: 含冒号拒绝
- **WHEN** 用户输入包含冒号的字符串（如 "a:b"）
- **THEN** 系统 SHALL 打印错误并重新提示，直到拿到合法值

#### Scenario: 启动时取消输入
- **WHEN** 用户在 user_id 提示处按 Ctrl+C 或 Ctrl+D
- **THEN** CLI SHALL 优雅退出，不创建任何 user / session

### Requirement: 运行中切换 user
CLI SHALL 支持 `/user <user_id>` 命令在运行时切换 user；切换后 sessions 列表 / current session / 提示符 SHALL 全部反映新 user。

#### Scenario: 切到已存在的 user
- **WHEN** 当前是 alice 且 bob 已有 sessions，用户输入 `/user bob`
- **THEN** 当前 user 切到 bob；`/sessions` 列出 bob 的 sessions；提示符变为 `[bob/...]`

#### Scenario: 切到不存在的 user
- **WHEN** 用户输入 `/user charlie`，charlie 在 sessions.json 中尚无任何记录
- **THEN** 系统 SHALL 自动为 charlie 创建空 bucket 并 bootstrap session-1，切到该 session

#### Scenario: 切前清理本轮 Teammate
- **WHEN** 用户输入 `/user bob`
- **THEN** 系统 SHALL 先调用 `team_manager.cleanup_spawned_in_turn()`，避免上一 user 的本轮 Teammate 残留

### Requirement: CLI 提示符显示 user / session
CLI 提示符 SHALL 形如 `[{user_id}/{session_id}] 你 > `，让用户清楚当前身份。

#### Scenario: 提示符渲染
- **WHEN** 当前 user=alice，session=session-2
- **THEN** 输入提示 SHALL 为 `[alice/session-2] 你 >`

### Requirement: leader.db 旧数据迁移
LeaderStore 在 `setup()` 末尾 SHALL 执行一次幂等迁移：将 `checkpoints` 与 `writes` 两张表中 `thread_id` 不含 `:` 的行的 `thread_id` 改为 `default:<原值>`。

#### Scenario: 首次启动有旧数据
- **WHEN** 首次启动且 leader.db 中存在若干 `thread_id = 'session-1'` 的行
- **THEN** 启动后这些行的 `thread_id` SHALL 变为 `default:session-1`，行数不变，内容不变

#### Scenario: 已迁移过的库再次启动
- **WHEN** leader.db 中所有 thread_id 都已含 `:`
- **THEN** 迁移 SHALL 是 no-op，不动任何行

#### Scenario: 迁移失败回滚
- **WHEN** 迁移过程中 SQL 执行失败
- **THEN** 事务 SHALL 回滚，leader.db 保持迁移前状态

### Requirement: sessions.json 旧格式迁移
SessionManager 在 `_load()` 中检测到旧格式（顶层不含 `users` 字段且含 `sessions` 字段）SHALL 自动转换为新格式（包到 `users.default` 下）并立即 `_save()`。

#### Scenario: 首次启动有旧 sessions.json
- **WHEN** 启动前 sessions.json 是 `{"current": "session-1", "sessions": [...]}`
- **THEN** 加载后内存结构 SHALL 为 `{"users": {"default": {"current": "session-1", "sessions": [...]}}}`；磁盘文件 SHALL 同步覆写

#### Scenario: 新格式不二次迁移
- **WHEN** sessions.json 已是新格式（含 `users` 字段）
- **THEN** 加载逻辑 SHALL 不触发迁移分支

### Requirement: user 间 session 完全隔离
不同 user 的 session 数据（leader.db 历史 + sessions.json 元数据）SHALL 完全不可见；同一 session_id 在不同 user 下 SHALL 各自独立存在。

#### Scenario: 同名 session 互不干扰
- **WHEN** alice 创建 session-1 写入 "我叫张三"，bob 也创建 session-1 写入 "我叫李四"
- **THEN** alice 切回 session-1 SHALL 看到 "张三"；bob 切回 session-1 SHALL 看到 "李四"

#### Scenario: 列表只显示当前 user
- **WHEN** 当前 user 是 alice，用户输入 `/sessions`
- **THEN** SHALL 仅列出 alice 的 sessions，不包含 bob / 其他 user 的
