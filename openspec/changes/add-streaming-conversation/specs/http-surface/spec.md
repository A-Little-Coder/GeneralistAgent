## ADDED Requirements

### Requirement: 能力清单接口

系统 SHALL 提供 `GET /api/capabilities` 路由，返回当前进程已注册的全部 SKILL 摘要（来自 `SkillRegistry.summary_table()`），结构 `{"capabilities": [{"name","description","type","triggers"}]}`；接口仅依赖 SkillRegistry，不发起 LLM 调用，响应应在 50ms 内完成。

#### Scenario: 正常返回

- **WHEN** 已注册 5 个 SKILL 后客户端 GET /api/capabilities
- **THEN** 响应 200，`capabilities` 列表长度为 5
- **AND** 每条含 `name / description / type / triggers` 字段

### Requirement: 就绪检查接口

系统 SHALL 提供 `GET /api/ready` 路由，依次检查 Redis ping、SQLite 连通、`get_chat_model("default")` 实例化、`SkillRegistry.is_ready()`，全部通过返回 200 + `{"status":"ready","checks":{...}}`；任一失败返回 503 + 统一错误响应格式，并在 `checks` 中标记失败项。

#### Scenario: 全部就绪

- **WHEN** 所有依赖正常
- **THEN** GET /api/ready 返回 200，`checks` 全为 true

#### Scenario: Redis 不通

- **WHEN** Redis 连接失败
- **THEN** GET /api/ready 返回 503
- **AND** 响应体符合统一错误格式 `{"error":{"code":"not_ready", ...}}`
- **AND** body 含 `checks.redis = false`

### Requirement: 用户反馈接口

系统 SHALL 提供 `POST /api/feedback` 路由，请求体 `{conv_id, plan_run_id, rating: "good"|"ok"|"bad", comment?: str}`，将反馈追加写入 `mem:conv:{conv_id}:feedback` 列表（每条含 `plan_run_id / rating / comment / created_at / user_id`），返回 `{"status":"ok"}`；同时 LangSmith trace 上对应 `plan_run_id` 的 root run 添加 tag `feedback=<rating>`。

#### Scenario: 写入成功

- **WHEN** 客户端 POST 合法 feedback
- **THEN** 响应 200 `{"status":"ok"}`
- **AND** Redis/SQLite 中 `mem:conv:{cid}:feedback` 列表新增 1 条
- **AND** LangSmith 中对应 plan_run trace 含 `feedback` tag

#### Scenario: rating 非法

- **WHEN** rating 不在枚举内
- **THEN** 响应 400，body 符合统一错误格式 `{"error":{"code":"invalid_input","message":"rating 必须是 good/ok/bad"}}`

#### Scenario: 反馈对象不存在

- **WHEN** plan_run_id 在系统中查不到对应 trace
- **THEN** 响应 404 `{"error":{"code":"plan_run_not_found", ...}}`

### Requirement: 会话列表接口

系统 SHALL 提供 `GET /api/conversations`，从 `SessionMemoryStore` 读取当前 user 的全部 conversation 元数据，返回 `{"conversations":[{"conv_id","title","last_active_at","message_count"}]}`，按 `last_active_at` 降序排列，分页参数 `limit`（默认 50，最大 200）/ `cursor`（可选）。

#### Scenario: 列出对话

- **WHEN** 用户已有 3 个对话
- **THEN** GET /api/conversations 返回 200，列表长度 3，按时间倒序

#### Scenario: 空用户

- **WHEN** 新用户首次访问
- **THEN** 返回 200 `{"conversations":[]}`

### Requirement: 对话标题自动生成

系统 SHALL 在某 `conv_id` 第一次完成 plan_run 后由 `ConversationStore.ensure_title(conv_id, first_query)` 把对话标题设为 `first_query` 截断到 30 个字符（按字符数，非字节数），尾部加 `…`（如有截断）；后续 plan_run 不再覆盖标题。

#### Scenario: 短 query

- **WHEN** 首条 query 长度为 12 字
- **THEN** title 为该 query 原文（不截断、不加省略号）

#### Scenario: 长 query

- **WHEN** 首条 query 长度为 50 字
- **THEN** title 为前 30 个字符 + `…`，总长度 31

#### Scenario: 后续 plan_run 不覆盖

- **WHEN** 同一 conv_id 第 2 次 plan_run 完成
- **THEN** title 保持第 1 次设定的值

### Requirement: 历史消息接口

系统 SHALL 提供 `GET /api/conversations/{cid}/messages?limit=50&before=<ts_ms>`，从 `SessionMemoryStore.get_history(cid, ...)` 读取历史消息列表，按时间倒序返回 `{"messages":[{"role","content","plan_run_id?","created_at"}], "has_more": bool}`；`limit` 默认 50、最大 200；`before` 是毫秒时间戳，用于游标分页。

#### Scenario: 默认拉取

- **WHEN** GET /api/conversations/c1/messages
- **THEN** 返回最近 50 条 message，按时间倒序
- **AND** 若历史超过 50 条，`has_more=true`

#### Scenario: 游标分页

- **WHEN** 第二页带 `before=<上页最后一条 created_at>`
- **THEN** 返回更早的 50 条

#### Scenario: 对话不存在

- **WHEN** cid 不存在
- **THEN** 响应 404 `{"error":{"code":"conversation_not_found", ...}}`

### Requirement: 删除对话接口

系统 SHALL 提供 `DELETE /api/conversations/{cid}`，调用 `SessionMemoryStore.clear(cid)` 删除会话历史 + 摘要 + 元数据 + 反馈列表（即所有 `mem:conv:{cid}:*` key）；不级联删除已结束 plan_run 的 LangSmith trace；返回 `{"status":"deleted"}`。

#### Scenario: 删除成功

- **WHEN** DELETE /api/conversations/c1
- **THEN** 响应 200 `{"status":"deleted"}`
- **AND** Redis/SQLite 中所有 `mem:conv:c1:*` key 已不存在

#### Scenario: 不存在的 cid

- **WHEN** cid 在存储中查不到
- **THEN** 响应 404 `{"error":{"code":"conversation_not_found", ...}}`

#### Scenario: 不级联 trace

- **WHEN** 该 conv 关联多个 plan_run trace
- **THEN** 删除后 LangSmith 中这些 trace 仍存在（不动 LangSmith）

### Requirement: 统一错误响应格式

系统 SHALL 通过 FastAPI 全局 `exception_handler` 把所有非 SSE 接口的 4xx / 5xx 错误响应统一为 `{"error":{"code","message","plan_run_id"}}` 格式：
- `code` 为 kebab-case 的错误码字符串（如 `rate_limited`、`invalid_input`、`conversation_not_found`、`not_ready`、`internal_error`）；
- `message` 中文可读消息；
- `plan_run_id` 在 plan_run 上下文中取实际值，否则空串。

SSE 接口的错误仍以事件流中 `type=error` 事件形式输出，不走此格式。

#### Scenario: 4xx 统一

- **WHEN** 任意接口返回 400/404/422/429
- **THEN** 响应体严格匹配上述 schema
- **AND** Content-Type 为 `application/json`

#### Scenario: 未捕获异常

- **WHEN** 处理函数抛出未声明异常
- **THEN** 响应 500
- **AND** body 为 `{"error":{"code":"internal_error","message":"...","plan_run_id":""}}`
- **AND** 错误信息已写日志（含完整 traceback）

### Requirement: 不引入 Request-Id 横切

系统 SHALL NOT 引入 `X-Request-Id` 头部、UUID 生成中间件、或任何"每次 HTTP 请求一个独立 id"的机制；所有定位与排查通过 `plan_run_id` 完成；前端在出问题时上报 `plan_run_id` 即可在 LangSmith 检索完整 trace。

#### Scenario: 未注入 Request-Id

- **WHEN** 任意接口请求与响应
- **THEN** 响应头不含 `X-Request-Id`
- **AND** 日志/trace 中不包含独立的 request_id 字段
