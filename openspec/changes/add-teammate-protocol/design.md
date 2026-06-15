## Context

历史上已建设的多个供应链 Agent（问数、预测、归因、报告等）需要被中控统一调用。决策已定：所有旧 Agent 一律以"Teammate Agent + 套壳 SKILL/MCP"方式接入；中控只通过 Teammate 接触它们，不直连旧服务。Teammate 在执行中可能要向用户反问（slot 缺失或方向不清），反问能力必须是通用组件，由 Teammate 触发但只能通过中控统一出口。

本 change 定义两件事：① Teammate 接入协议（目录结构、生命周期、重试）；② 反问通用组件（队列、二分类型、选择/填空两类模板）。

## Goals / Non-Goals

**Goals:**
- 定义 Teammate 接入协议：每个 Teammate = `skills/teammates/<name>/` 一个目录，含 `SKILL.md` + `client.py` + 可选 prompts
- 实现 Teammate 临时拉起（per-turn）与统一重试（默认 1 次，`max_retries` 可在 SKILL.md 配置）
- 实现反问通用组件：`raise_question` 工具、中控侧 `AskBackInterruptHandler`、`AskBackQueue`（FIFO，串行 pop）
- 反问 payload 二分类（`slot_fill` / `replan`）+ 形式二分类（`ChoiceAskBack` / `FillAskBack`）
- 提供 `ask_data` 示例 Teammate 作为参考实现与测试样板

**Non-Goals:**
- 不实现 SSE 协议本身（在 `add-streaming-conversation`）
- 不实现规划层（在 `add-orchestrator-planner`）
- 不实现具体的旧 Agent 业务逻辑，仅 mock HTTP 调用

## Decisions

### 决策 1：Teammate 目录与基类

```
skills/teammates/<name>/
├── SKILL.md              # frontmatter：type=teammate, runtime=http|mcp
├── client.py             # 必需：实现 call(payload) -> Result
├── prompts/system.md     # 可选：套壳 LLM 时的 system prompt
└── examples.json         # 可选
```

```python
# chatbi/capabilities/teammates/base.py
class TeammateBase(ABC):
    name: str
    spec: SkillSpec

    @abstractmethod
    async def call(self, payload: dict, ctx: TeammateContext) -> TeammateResult: ...

    async def raise_question(self, ev: AskBackEvent) -> str:
        # 透传到中控的反问组件
        return await ctx.ask_back.raise_and_wait(ev)
```

- 每个 Teammate 子类实现自己的 `client.py`，封装对旧服务的 HTTP/MCP 调用
- `TeammateContext` 注入 `ask_back`、`logger`、`trace_metadata`、`plan_run_id`，由中控在拉起时构造

### 决策 2：临时拉起（per-turn）

- 每次 plan_run 在执行节点要调用某 Teammate 时，由 `TeammateFactory.spawn(name, ctx)` 构造实例
- 实例生命周期 = 一次工具调用，调用结束（成功/失败/超时）即销毁
- 不做预热池，不复用实例
- 理由：实现简单、隔离干净；冷启动开销小（实例化 + HTTP client 复用全局连接池）

### 决策 3：统一重试

- 默认 `max_retries=1`，可在 `SKILL.md` 字段 override
- 用 `tenacity` 实现：仅对网络错误 / 5xx / 超时重试，不对业务 4xx 重试
- 每次重试在 LangSmith span 标 `retry_attempt=k`
- 重试间隔：指数退避 `0.5 * 2^k`，最大 5s
- 全部重试用尽仍失败 → 抛 `TeammateCallError`，中控决定是否重规划或返回"能力不足"

### 决策 4：反问组件总体架构

```
┌──────────────────────────────────────────────────────────┐
│  Teammate (执行中)                                          │
│   raise_question(ev: AskBackEvent) ──► raise_and_wait()    │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│  AskBackHub (plan_run 级单例)                               │
│   ├── queue: AskBackQueue (FIFO)                           │
│   ├── current: 当前未决反问                                  │
│   └── futures: dict[event_id → Future]                     │
└─────────────────────────┬────────────────────────────────┘
                          │ enqueue
                          ▼
┌──────────────────────────────────────────────────────────┐
│  AskBackInterruptHandler (中控侧)                           │
│   - 取出 queue 头部                                         │
│   - 通过 LangGraph interrupt() 暂停                          │
│   - 把 event 上抛到 SSE 出口（事件 type=ask_back）             │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼ 用户回答经 /api/chat/resume
┌──────────────────────────────────────────────────────────┐
│  resume(event_id, user_answer)                              │
│   - 根据 resume_strategy:                                    │
│       slot_fill → set_result(future)，回到 Teammate 继续      │
│       replan    → set_result + 标记 plan_run.replan_needed   │
│   - 处理下一个未决反问（如果队列还有）                           │
└──────────────────────────────────────────────────────────┘
```

### 决策 5：反问类型二分

| resume_strategy | 触发场景 | 处理 |
|---|---|---|
| `slot_fill` | 缺一个明确入参（如时间口径） | 续跑，把答案塞回 Teammate.call 的入参 |
| `replan` | 任务方向不清（用户问太宽） | 答完后丢弃当前 plan，回到规划节点，把答案附加到上下文 |

### 决策 6：反问形式二分（模板类）

```python
# chatbi/infra/ask_back/events.py
class AskBackEvent(BaseModel):
    event_id: str
    teammate_id: str | None     # None = 中控自己问
    slot: str
    question: str
    resume_strategy: Literal["slot_fill", "replan"]
    type: Literal["choice", "fill"]   # 区分形式

class ChoiceAskBack(AskBackEvent):
    type: Literal["choice"] = "choice"
    options: list[str]
    multi_select: bool = False

class FillAskBack(AskBackEvent):
    type: Literal["fill"] = "fill"
    placeholder: str | None = None
    validator: str | None = None     # 可选预设校验器名（如 "iso_date"）
```

- 前端按 `type` 字段一次分支渲染（选择按钮 / 输入框）
- `validator` 仅做轻量预设（日期、数字、非空），失败用户重新输入；不做严格校验避免阻塞

### 决策 7：嵌套与队列

- 同一 plan_run 内多 Teammate 可能并发 / 嵌套触发反问
- `AskBackQueue` 用 `asyncio.Queue` 维护未决事件
- **同一时刻只 pop 一个推前端**，前一个 resolve 后再处理下一个
- 触发反问的 Teammate `await future.set_result()`；其他 Teammate 同步内容继续阻塞 `raise_and_wait`
- 队列上限：默认 8，超出抛 `AskBackQueueFullError`，中控以 `replan` 兜底

### 决策 8：raise_question 工具注入

- `to_deepagents_kwargs` 适配层（在 `add-skill-registry`）会给每个 `type=teammate` 的 subagent 自动注入 `raise_question` 工具
- 工具签名：`raise_question(slot: str, question: str, resume_strategy: str = "slot_fill", type: str = "fill", **kwargs)`
- 工具内部：构造对应 `AskBackEvent` → 调 `ctx.ask_back.raise_and_wait()` → 返回用户回答字符串

## Risks / Trade-offs

- [Risk] LangGraph interrupt + 队列在多 Teammate 并发场景下顺序难调试 → Mitigation：所有 enqueue/dequeue/resolve 上 LangSmith span，前端开发模式可看队列状态
- [Risk] 用户长时间不回答 → Mitigation：默认 30 分钟超时，超时后 plan_run 失败并清理队列
- [Risk] tenacity 与 LangSmith span 嵌套层级混乱 → Mitigation：每次重试用 LangSmith `as_runnable` 包一层独立 span
- [Trade-off] 临时拉起每次重新创建 client = 轻量内存开销；HTTP 连接池全局共享，性能影响可忽略

## Migration Plan

- 新建项目，无迁移
- 后续若新增非 HTTP/MCP 的旧 Agent（如 grpc），扩展 `Runtime` 枚举与基类即可

## Open Questions

- 反问超时（30 分钟）是否需在 SKILL.md 可配？暂不放，避免配置面过宽
- 是否要支持"撤销反问"（Teammate 中途发现不需要问了）？暂不支持，复杂度收益比不高
