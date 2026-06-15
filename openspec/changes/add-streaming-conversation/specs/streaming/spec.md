## ADDED Requirements

### Requirement: SSE 流式接口

系统 SHALL 提供 `POST /api/chat/stream` 路由，请求体含 `query`、`conv_id?`、`plan_run_id?`，响应使用 SSE（`Content-Type: text/event-stream`），事件按 `EventNormalizer` 输出的标准 schema 序列化为 `data: <json>\n\n`。

#### Scenario: 简单问答端到端

- **WHEN** 客户端 POST 一个简单问题
- **THEN** 服务端依次推送 `node_enter` / `token`*N / `node_exit` / `final` 事件
- **AND** 最后流自然关闭

### Requirement: 标准事件 schema

系统 SHALL 输出以下类型事件，每个事件含 `type / ts / plan_run_id / data` 顶层字段：`token`、`node_enter`、`node_exit`、`tool_call_start`、`tool_call_end`、`ask_back`、`final`、`error`、`heartbeat`。`data` 字段子结构遵循 design 决策 2。

#### Scenario: 类型 schema 校验

- **WHEN** 测试遍历每个 type
- **THEN** 用 pydantic 模型 `StandardEvent` 校验通过

### Requirement: EventNormalizer

系统 SHALL 在 `chatbi/conversation/event_normalizer.py::EventNormalizer.normalize(raw)` 把 LangGraph `astream_events` 输出归一为 `StandardEvent`；同时合并来自 `AskBackHub.events_iter()` 的反问事件。

#### Scenario: 多路合并

- **WHEN** LangGraph 推 token 同时 AskBackHub 入队反问
- **THEN** Normalizer 输出按时间顺序合并的事件流

### Requirement: 心跳与断开取消

系统 SHALL 每 30 秒发送 `heartbeat` 事件（SSE comment 形式），并在 `request.is_disconnected()` 检测到断开后取消正在运行的 LangGraph 任务（调用 `task.cancel()`）。

#### Scenario: 30 秒心跳

- **WHEN** 服务端无新事件 31 秒
- **THEN** 至少有一个 heartbeat 事件被推送

#### Scenario: 客户端断开取消

- **WHEN** 客户端关闭 SSE 连接
- **THEN** LangGraph task 被取消
- **AND** 对应 plan_run 状态置为 `cancelled`