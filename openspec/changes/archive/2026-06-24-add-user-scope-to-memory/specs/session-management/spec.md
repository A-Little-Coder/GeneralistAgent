## MODIFIED Requirements

### Requirement: Session 元数据管理
系统 SHALL 维护一个 `SessionManager`，持久化 user 列表与每 user 的 session 列表 / current session 到 `memory/sessions.json`；每个 session 包含 `id` / `title` / `created_at` / `last_active_at` 字段。SessionManager 持有 `current_user_id` 状态，所有公开方法（list / new / switch / delete / rename / set_title_if_empty / bootstrap）SHALL 隐式作用于该 current user。

#### Scenario: 元数据持久化
- **WHEN** 用户新建一个 session 后退出 CLI
- **THEN** `memory/sessions.json` 的 `users.<current_user_id>.sessions` 列表 SHALL 包含该 session 的完整元数据

#### Scenario: 启动加载 user 列表
- **WHEN** CLI 启动且 `sessions.json` 存在且包含 `users` 字段
- **THEN** 全部 user 数据 SHALL 被加载，CLI 输入的 user_id 设为 current；该 user 不存在时自动 bootstrap

### Requirement: 首启自动建 session-1
对每个 user，若 sessions.json 中该 user 尚无任何 session，SessionManager.bootstrap() SHALL 为其创建一个名为 `session-1` 的空 session 并设为该 user 的 current。

#### Scenario: 全新 user 首次进入
- **WHEN** CLI 启动输入 user_id="alice"，sessions.json 中 alice 尚未存在
- **THEN** SHALL 为 alice 创建空 bucket，bootstrap 出 session-1 并设为 alice 的 current

#### Scenario: 已有 user 重新进入
- **WHEN** alice 已有 3 个 session，再次启动输入 alice
- **THEN** SHALL 沿用磁盘上 alice 的 current，不重复 bootstrap

### Requirement: Session 标题取首条消息前 20 字
新建 session 的 `title` SHALL 在用户首条消息提交时自动生成：取消息内容 strip 后前 20 个 Unicode 字符；若原文超过 20 字符 SHALL 末尾追加 `…`。后续消息 SHALL **不**触发标题更新。

#### Scenario: 短消息作标题
- **WHEN** session 的 title 为空，用户提交首条消息 "你好"
- **THEN** session.title SHALL 为 "你好"

#### Scenario: 长消息截断作标题
- **WHEN** session 的 title 为空，用户提交首条消息为 25 字符的中文长句
- **THEN** session.title SHALL 取前 20 字符 + `…`

#### Scenario: 已有标题不再更新
- **WHEN** session.title 已存在，用户提交第二条消息
- **THEN** session.title SHALL 保持不变

### Requirement: Session 切换命令
CLI SHALL 支持以下命令操作当前 user 的 session：`/new`、`/sessions`（或 `/list`）、`/switch <id|序号>`、`/delete <id|序号>`、`/title <new_title>`。所有命令 SHALL 仅作用于 current user 的 session 列表。

#### Scenario: /new 切话题
- **WHEN** 用户输入 `/new`
- **THEN** SHALL 在 current user 下创建新 session、设为该 user 的 current、提示空对话

#### Scenario: /sessions 列出
- **WHEN** 用户输入 `/sessions`
- **THEN** CLI SHALL 仅打印 current user 的所有 session 的序号、id、title、last_active_at，标记 current

#### Scenario: /switch 切换
- **WHEN** 用户输入 `/switch 2`
- **THEN** SHALL 切到 current user 列表第 2 个 session

#### Scenario: /title 改名
- **WHEN** 用户输入 `/title 新标题`
- **THEN** current user 的 current session 的 title SHALL 被更新

### Requirement: 删除 session 同步清 checkpoint
`/delete <session>` SHALL 先确认（默认 No），确认后用复合 thread_id（`{current_user_id}:{session_id}`）调用 `LeaderStore.purge` 从 `leader.db` 删除该 thread_id 的所有 checkpoint，再从 sessions.json 的 current user 桶中移除该条；若删除当前 session SHALL 自动切到该 user 列表第一个剩余 session（若无剩余则为该 user 创建新的 session-1）。

#### Scenario: 删除非当前 session
- **WHEN** 用户输入 `/delete 3` 并确认
- **THEN** sessions.json 中 current user 桶 SHALL 移除该 session；leader.db 中 `{current_user_id}:{session_id}` 的 checkpoint SHALL 全部删除

#### Scenario: 删除当前 session
- **WHEN** 用户输入 `/delete <current>` 并确认
- **THEN** SHALL 删除后自动切到该 user 首个剩余 session 或新建 session-1

#### Scenario: 删除不影响其他 user
- **WHEN** alice 删除自己的 session-1
- **THEN** bob 的 session-1 SHALL 不受影响（leader.db 中 `bob:session-1` 仍在）
