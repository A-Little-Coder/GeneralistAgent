## Context

会话层是 ChatBI Web Chat 入口与中控 Agent 之间的桥梁，负责：① 接收用户问题、② 流式输出思考与回答、③ 反问中断与续跑、④ 限流排队、⑤ 取消/心跳；同时配套若干轻量 HTTP 接口（能力清单、就绪检查、用户反馈、会话历史）以支撑前端体验。前端期望 SSE 协议，且事件粒度需细到 token、节点、工具调用与反问，以便渲染思考过程。

deepagents 基于 LangGraph，原生有 `astream_events`，可拿到细粒度事件，但格式繁杂（v1 / v2 schema），需要做事件标准化层。反问事件来自 `add-teammate-protocol` 的 `AskBackHub`，本 change 负责把它们桥接到 SSE。

服务定位：内部服务，前端与 ChatBI Agent 同公司同内网，认证由上游网关完成（注入 `X-User-Id`），不引入项目侧的认证 / 鉴权 / API 版本化 / API key 等机制。

## Goals / Non-Goals

**Goals:**
- FastAPI 路由 `POST /api/chat/stream`（SSE）与 `POST /api/chat/resume`、`POST /api/chat/cancel`
- `EventNormalizer`：统一事件 schema（`token / node_enter / node_exit / tool_call_start / tool_call_end / ask_back / final / error / heartbeat`）
- 反问中断协议 + 续跑：恢复 plan_run state 后 resume(answer)
- 进程级 + 用户级令牌桶限流（默认 5 QPS / user，10 并发 / 进程）
- 心跳保活（30s SSE comment）
- 客户端断开取消 LangGraph 执行
- LangSmith：每对话一 trace；反问、续跑、限流、取消事件作为 span
- 轻量 HTTP 接口集（http-surface 能力）：`GET /api/capabilities`、`GET /api/ready`、`POST /api/feedback`、`GET /api/conversations`、`GET /api/conversations/{cid}/messages`、`DELETE /api/conversations/{cid}`
- 统一错误响应格式 `{"error":{"code","message","plan_run_id"}}`，覆盖所有 4xx/5xx
- 对话标题：首条 query 前 30 字自动生成

**Non-Goals:**
- 不做前端 UI
- 不做认证 / 鉴权 / 多租户 / API 版本化（user_id 由网关注入 header `X-User-Id`）
- 不引入 `X-Request-Id` 横切；定位与排查全部使用 `plan_run_id`
- 不实现 WebSocket（仅 SSE，更轻）
- 不做对话重命名（暂不需求）

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

POST /api/chat/cancel
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
- **统一错误响应格式**（适用所有非 SSE 接口的 4xx/5xx）：

  ```json
  {
    "error": {
      "code": "rate_limited | not_found | invalid_input | internal_error | conversation_not_found | ...",
      "message": "中文可读消息",
      "plan_run_id": "..."   // 若不在 plan_run 上下文，则空串
    }
  }
  ```

  通过 FastAPI `exception_handler` 统一拦截 `HTTPException` 与未捕获异常输出此格式。

### 决策 8：HTTP 配套接口（http-surface）

为 Web Chat 前端配套的轻量接口（非 SSE）。前端典型生命周期：

```
打开聊天页
  GET /api/capabilities          → 显示"我能干什么"提示
  GET /api/conversations         → 左侧栏对话列表

点开某条对话
  GET /api/conversations/{cid}/messages?limit=50&before=<ts>
                                 → 拉取分页历史消息

发起新对话或新一轮
  POST /api/chat/stream          → SSE 主入口
  ...（必要时 /resume）

用户对某条回答点"优/一般/差"
  POST /api/feedback
       {conv_id, plan_run_id, rating: "good"|"ok"|"bad", comment?: str}

用户右键删除一条对话
  DELETE /api/conversations/{cid}

异常排查
  GET /api/ready                 → 探依赖（Redis/SQLite/LLM）就绪
```

**对话标题生成策略（决策 8.1）**：

- conversation 在第 1 条用户 query 完成 plan_run 后由 `ConversationStore` 自动设置 `title = query[:30]`（截断到 30 个字符，含中文）
- 后续轮不再更新 title
- 不引入 LLM 生成标题（节流，业务后期可升级）

**反馈对象（决策 8.2）**：

- 反馈接口的定位主键统一使用 `plan_run_id`（一次完整问答 = 一个 plan_run）
- 跨 `/stream` + `/resume` 的反问续跑场景仍然指向同一个 `plan_run_id`
- 不引入 `message_id` 或 `request_id` 这类多余概念，前端从 SSE 流的事件里直接取 `plan_run_id` 即可
- feedback 数据写入 `mem:conv:{cid}:feedback` 列表（key 命名复用 `add-memory-persistence` 的规范）

**对话数据来源（决策 8.3）**：

- 对话列表与历史消息直接读取 `add-memory-persistence` 提供的 `SessionMemoryStore`，本 change 仅做 HTTP 包装
- 删除 = 调 `SessionMemoryStore.clear(conv_id)` + 删除 conv 元数据 key
- 历史消息分页：按时间倒序，`limit` 默认 50，最大 200；`before` 参数为时间戳（ms）

**就绪检查（决策 8.4）**：

- `/api/ready` 检查项：Redis ping、SQLite 连通、`get_chat_model("default")` 实例化成功（不发请求）、`SkillRegistry.is_ready()`
- 任一失败返回 503 + 统一错误格式
- 不替代 `/healthz`（仍存在，仅检查进程存活）

## Risks / Trade-offs

- [Risk] LangGraph `astream_events` v1/v2 schema 变化 → Mitigation：EventNormalizer 单独一文件可独立升级；测试覆盖两版本
- [Risk] SSE 长连+反代不稳 → Mitigation：心跳 + 客户端断开自动恢复
- [Risk] 用户级限流的状态在多进程下无法共享 → Mitigation：当前单实例部署；限流状态仅进程内即可，迁移到 Redis 后统一
- [Risk] 标题取首 30 字遇到表情/特殊字符截断不雅 → Mitigation：用 `len()` 按字符数（不按字节）截断，trailing 加 `…`
- [Trade-off] 不实现 WebSocket：未来如需服务端主动推（无 user query 触发）再考虑
- [Trade-off] 不引入 X-Request-Id：内部服务用 plan_run_id 已足够定位；外部排查时让前端把 plan_run_id 报上来即可

## Migration Plan

- 新建项目，无迁移
- 与前端协议一致后再调整事件字段

## Open Questions

- 限流策略是否要支持每天/每小时配额（不仅每秒）？暂不实现，先满足秒级限流
- 是否要在 final 事件中带规划 plan 用于前端展示？暂不带，避免暴露内部细节
- 反馈是否需要支持"撤销"或"修改"？暂不支持，前端"优/一般/差"为最后一次写入即可