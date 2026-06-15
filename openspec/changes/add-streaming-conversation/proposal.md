## Why

Web Chat 主入口要求实时流式输出（思考过程、工具调用、最终回答），并且要支持反问中断/续跑、限流排队等会话级行为。同时反问事件、节点事件、token 事件必须有统一协议，前端才能稳定渲染。借助 deepagents（基于 LangGraph）的 `astream_events`，可以拿到细粒度事件，但需要做事件标准化与 SSE 协议层。

## What Changes

- 实现 SSE Endpoint（FastAPI 路由 `/api/chat/stream`），消费 LangGraph `astream_events`
- 实现 `EventNormalizer`：把 LangGraph 原始事件归一为标准事件 `token / node_enter / node_exit / tool_call_start / tool_call_end / ask_back / final / error`
- 实现反问中断与前端协议：SSE 推 `ask_back` 事件 → 前端展示 → 用户回答经 `/api/chat/resume` 接口回灌 LangGraph
- 实现续跑：基于 `plan_run_id` 从持久化层（`add-memory-persistence`）恢复 LangGraph 状态后 `resume(answer)`
- 实现限流排队：进程级 `asyncio.Semaphore` + 用户级令牌桶（默认 5 QPS / 用户），超限返回 429 或排队
- 实现取消：用户主动断开 SSE 连接 → 触发 LangGraph 取消 → 释放 Teammate 资源
- 实现心跳保活：30s 一次 SSE comment，避免代理断连
- LangSmith 接入：每个对话一个 trace，反问事件、续跑事件作为 span 上报
- 提供轻量 HTTP 接口集（前端配套）：能力清单、就绪检查、用户反馈、会话列表/历史/删除
- 统一错误响应格式 `{"error":{"code","message","plan_run_id"}}`，所有 4xx/5xx 一致
- 对话标题：首条 query 前 30 字自动生成

## Capabilities

### New Capabilities

- `streaming`: SSE 流式输出与事件标准化
- `interrupt-resume`: 反问中断 / 用户回答 / 续跑机制
- `rate-limiting`: 进程级 + 用户级限流排队
- `http-surface`: 配套 HTTP 接口集（能力清单 / 就绪检查 / 反馈 / 会话管理）+ 统一错误响应

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/conversation/`（sse、event_normalizer、interrupt、rate_limit、router）
- 影响依赖：新增 `fastapi`、`uvicorn`、`sse-starlette`
- 依赖前置：`add-chatbi-foundation`、`add-memory-persistence`、`add-teammate-protocol`（反问事件协议）、`add-orchestrator-planner`（执行图）
