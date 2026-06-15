## ADDED Requirements

### Requirement: LangSmith 接入初始化

系统 SHALL 在 CLI 与 FastAPI 启动时由 `chatbi.observability.langsmith_setup.init()` 完成 LangSmith 接入：读取 `LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`、设置 `LANGCHAIN_TRACING_V2=true`、初始化默认 Tracer 与 Run name 模板，并以 5 秒超时探测 LangSmith 端点。

#### Scenario: 完整凭证启动

- **WHEN** `.env` 中 `LANGSMITH_API_KEY` 与 `LANGSMITH_PROJECT` 均存在
- **THEN** `init()` 返回 `True`
- **AND** 启动日志输出「LangSmith 接入成功，项目：chatbi-dev」

#### Scenario: 缺失凭证不阻塞启动

- **WHEN** `LANGSMITH_API_KEY` 未配置
- **THEN** `init()` 返回 `False`
- **AND** 启动日志输出 WARNING 「未检测到 LANGSMITH_API_KEY，本次运行不上报追踪」
- **AND** 进程继续运行不抛异常

### Requirement: 项目命名约定

系统 SHALL 按 `chatbi-{env}` 模式命名 LangSmith 项目，`{env}` 取值为 `dev` / `staging` / `prod`，从环境变量 `CHATBI_ENV` 读取，缺失时默认 `dev`。

#### Scenario: 默认环境

- **WHEN** 未设置 `CHATBI_ENV` 与 `LANGSMITH_PROJECT`
- **THEN** 实际生效项目名为 `chatbi-dev`

### Requirement: hello-trace 验证

系统 SHALL 提供 `chatbi hello-trace` CLI 子命令，调用 `get_chat_model("default")` 发起一次最小问答（提示词："请用中文回复：你好"），并在 LangSmith 后台产出至少 1 条名为 `hello-trace` 的 trace。

#### Scenario: 最小验证通过

- **WHEN** 配置好凭证后执行 `chatbi hello-trace`
- **THEN** 进程退出码 0
- **AND** stdout 打印模型回答与 LangSmith 后台 trace URL

### Requirement: Trace 元数据注入

系统 SHALL 在每次 LLM / 工具调用时自动注入元数据 `user_id`、`conv_id`、`plan_run_id`、`retry_attempt`（缺失为空字符串），通过 LangChain `RunnableConfig` 的 `metadata` 字段传递；元数据获取由 `chatbi.observability.context.get_trace_context()` 统一管理。

#### Scenario: 上下文为空时

- **WHEN** 直接执行 `hello-trace`，未进入会话上下文
- **THEN** trace 的 metadata 包含上述 4 个字段且值为空字符串
- **AND** 不抛异常

### Requirement: LLM 工厂 LangSmith 自动埋点

系统 SHALL 在 `get_chat_model(name)` 中默认 `temperature` 等参数可配置、强制 `callbacks` 至少包含 LangSmith Tracer，使任何调用方拿到的模型实例都自动产生 LangSmith trace。

#### Scenario: 工厂返回的模型自动埋点

- **WHEN** 业务代码调用 `get_chat_model("default").invoke("hi")`
- **THEN** LangSmith 后台立即出现一条对应 trace
