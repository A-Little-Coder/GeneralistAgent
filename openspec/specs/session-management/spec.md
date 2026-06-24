## ADDED Requirements

### Requirement: Session 元数据管理
系统 SHALL 维护一个 `SessionManager`，持久化 session 列表与当前 session 到 `memory/sessions.json`；每个 session 包含 `id` / `title` / `created_at` / `last_active_at` 字段。

#### Scenario: 元数据持久化
- **WHEN** 用户新建一个 session 后退出 CLI
- **THEN** `memory/sessions.json` SHALL 包含该 session 的完整元数据

#### Scenario: 启动加载 current
- **WHEN** CLI 启动且 `sessions.json` 存在且包含 `current` 字段
- **THEN** SHALL 自动进入该 current session

### Requirement: 首启自动建 session-1
若 `memory/sessions.json` 不存在或 sessions 列表为空，SessionManager SHALL 在启动时自动创建一个名为 `session-1` 的空 session 并设为 current。

#### Scenario: 首次启动
- **WHEN** 用户首次启动 CLI，`memory/sessions.json` 不存在
- **THEN** SHALL 创建 session-1 并进入；CLI 提示符 SHALL 显示当前 session 名

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
CLI SHALL 支持以下命令操作 session：`/new`、`/sessions`（或 `/list`）、`/switch <id|序号>`、`/delete <id|序号>`、`/title <new_title>`。

#### Scenario: /new 切话题
- **WHEN** 用户输入 `/new`
- **THEN** SHALL 创建新 session、设为 current、提示空对话

#### Scenario: /sessions 列出
- **WHEN** 用户输入 `/sessions`
- **THEN** CLI SHALL 打印所有 session 的序号、id、title、last_active_at，标记 current

#### Scenario: /switch 切换
- **WHEN** 用户输入 `/switch 2`
- **THEN** SHALL 切到列表第 2 个 session，下一轮对话从该 session 历史继续

#### Scenario: /title 改名
- **WHEN** 用户输入 `/title 新标题`
- **THEN** current session 的 title SHALL 被更新为 "新标题"

### Requirement: 删除 session 同步清 checkpoint
`/delete <session>` SHALL 先确认（默认 No），确认后调用 `LeaderStore.purge(session_id)` 从 `leader.db` 删除该 thread_id 的所有 checkpoint，再从 sessions.json 移除该条；若删除当前 session SHALL 自动切到列表第一个剩余 session（若无剩余则创建新的 session-1）。

#### Scenario: 删除非当前 session
- **WHEN** 用户输入 `/delete 3` 并确认
- **THEN** sessions.json SHALL 移除该 session、leader.db 中该 thread_id 的 checkpoint SHALL 全部删除

#### Scenario: 删除当前 session
- **WHEN** 用户输入 `/delete <current>` 并确认
- **THEN** SHALL 删除后自动切到首个剩余 session 或新建 session-1

#### Scenario: 取消删除
- **WHEN** 用户输入 `/delete N`，确认提示输入 N
- **THEN** SHALL 不删除任何内容
