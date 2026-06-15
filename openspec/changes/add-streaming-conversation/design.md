## Context

会话层是 ChatBI Web Chat 入口与中控 Agent 之间的桥梁，负责：① 接收用户问题、② 流式输出思考与回答、③ 反问中断与续跑、④ 限流排队、⑤ 取消/心跳。前端期望 SSE 协议，且事件粒度需细到 token、节点、工具调用与反问，以便渲染思考过程。

deepagents 基于 LangGraph，原生有 `astream_events`，可拿到细粒度事件，但格式繁杂（v1 / v2 schema），需要做事件标准化层。反问事件来自 `add-teammate-protocol` 的 `AskBackHub`，本 change 负责把它们桥接到 SSE。

## Goals / Non-Goals

**Goals:**
- FastAPI 路由 `POST /api/chat/stream`（SSE）与 `POST /api/chat/resume`
- `EventNormalizer`：统一事件 schema（`token / node_enter / node_exit / tool_call_start / tool_call_end / ask_back / final / error / heartbeat`）
- 反问中断协议 + 续跑：恢复 plan_run state 后 resume(answer)
- 进程级 + 用户级令牌桶限流（默认 5 QPS / user，10 并发 / 进程）
- 心跳保活（30s SSE comment）
- 客户端断开取消 LangGraph 执行
- LangSmith：每对话一 trace；反问、续跑、限流、取消事件作为 span

**Non-Goals:**
- 不做前端 UI
- 不做认证（user_id 由网关注入 header `X-User-Id`，后续 change 可加）
- 不实现 WebSocket（仅 SSE，更轻）

## Decisions

### 决策 1：API 协议

```
POST /api/chat/stream
Headers:  X-User-Id (网关注入)
Body:     {conv_id?, query, plan_run_id?}
Response: SSE 流 (Content-Type: text/event-stream)

POST /api/chat/resume
Body:     {plan_run_id, event_id, answer}
Response: 同 /stream（继续推送事件）

GET /api/chat/cancel
Body:     {plan_run_id}
Response: {"status":"cancelled"}
```

### 决策 2：标准事件 schema

```json
{
  "type": "token | node_enter | node_exit | tool_call_start | tool_call_end | ask_back | final | error | heartbeat",
  "ts": 1718000000.123,
  "plan_run_id": "...",
  "data": { ... type-specific ... }
}
```

具体类型 data：
- `token`: `{content: str, model: str}`
- `node_enter` / `node_exit`: `{node_name: str, elapsed_ms?: int}`
- `tool_call_start`: `{tool_name, args}`
- `tool_call_end`: `{tool_name, output, error?}`
- `ask_back`: `{event_id, type:"choice"|"fill", question, slot, options?, multi_select?, placeholder?, validator?, resume_strategy}`
- `final`: `{answer: str, citations?: list}`
- `error`: `{code, message}`
- `heartbeat`: `{}`

### 决策 3：EventNormalizer 实现

```python
class EventNormalizer:
    async def normalize(self, raw_events) -> AsyncIterator[StandardEvent]:
        async for ev in raw_events:
            if ev["event"] == "on_chat_model_stream":
                yield StandardEvent(type="token", data={"content": ev["data"]["chunk"].content})
            elif ev["event"] == "on_chain_start":
                yield StandardEvent(type="node_enter", data={"node_name": ev["name"]})
            elif ev["event"] == "on_chain_end":
                yield StandardEvent(type="node_exit", data={"node_name": ev["name"]})
            elif ev["event"] == "on_tool_start":
                yield StandardEvent(type="tool_call_start", data={...})
            elif ev["event"] == "on_tool_end":
                yield StandardEvent(type="tool_call_end", data={...})
            # 反问事件来自单独 channel（AskBackHub 推送）
```

### 决策 4：反问中断与续跑

```
[/api/chat/stream]
    │
    ├── 启动 plan_run，注入 AskBackHub 实例
    ├── 启动事件复用：合并 (LangGraph events) + (AskBackHub events) 两路
    │
    ├── LangGraph 执行 → 触发 raise_question
    │    │
    │    ├── AskBackHub enqueue → handler interrupt()
    │    └── EventNormalizer 推 ask_back 事件
    │
    ├── SSE 把 ask_back 事件推到前端 → 流暂停（图已 interrupt）
    └── HTTP 连接保持（SSE 长连）

[/api/chat/resume]
    │
    ├── 找到对应 plan_run（从 BlackboardStore + state checkpoint）
    ├── AskBackHub.resume(event_id, answer)
    └── 通知原 SSE 流继续推送（事件复用器醒来）
```

实现要点：
- LangGraph state 在 interrupt 时由 `CheckpointSaver` 持久化（`add-memory-persistence` 提供的 SQLite/Redis 都可作为后端）
- `/resume` 不创建新 SSE 流，而是把 answer 写入 hub，让原流继续推
- 若原 SSE 已断开（用户刷新页面），`/resume` 启动新 SSE 流（从 checkpoint 恢复）

### 决策 5：限流

```
进程级：asyncio.Semaphore(10)  # 同时进行的 plan_run 数量
用户级：令牌桶（容量=5, 每 1s 加 1 个）
```

- 超限返回 `429 Too Many Requests` 或排队（队列上限 30 / 用户）
- 限流事件上报 LangSmith span

### 决策 6：心跳与取消

- SSE 30s 一次 comment（`: heartbeat\n\n`），避免反代/防火墙断连
- 客户端断开（asgi `request.is_disconnected()` 检测）→ 取消 LangGraph task → 释放 Teammate 资源

### 决策 7：错误处理

- 任何未捕获异常 → 推 `error` 事件 → 关闭 SSE
- LangGraph 内部错误 → `tool_call_end` 含 `error` 字段 → 继续推流（让上游决定是否中断）
- 严重错误 → 直接 `final` + `error`

## Risks / Trade-offs

- [Risk] LangGraph `astream_events` v1/v2 schema 变化 → Mitigation：EventNormalizer 单独一文件可独立升级；测试覆盖两版本
- [Risk] SSE 长连+反代不稳 → Mitigation：心跳 + 客户端断开自动恢复
- [Risk] 用户级限流的状态在多进程下无法共享 → Mitigation：当前单实例部署；限流状态仅进程内即可，迁移到 Redis 后统一
- [Trade-off] 不实现 WebSocket：未来如需服务端主动推（无 user query 触发）再考虑

## Migration Plan

- 新建项目，无迁移
- 与前端协议一致后再调整事件字段

## Open Questions

- 限流策略是否要支持每天/每小时配额（不仅每秒）？暂不实现，先满足秒级限流
- 是否要在 final 事件中带规划 plan 用于前端展示？暂不带，避免暴露内部细节