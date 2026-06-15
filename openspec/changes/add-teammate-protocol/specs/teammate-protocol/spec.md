## ADDED Requirements

### Requirement: Teammate 套壳目录约定

系统 SHALL 要求每个 Teammate 以独立目录形式置于 `skills/teammates/<name>/`，目录至少包含 `SKILL.md`（`type=teammate`）；当 `runtime` 为 `http` 或 `mcp` 时必须额外提供 `client.py` 实现 `Client.call(payload, ctx) -> dict` 协程函数。

#### Scenario: 缺失 client.py

- **WHEN** `runtime: http` 但目录无 `client.py`
- **THEN** 启动失败，错误中文指出该目录缺 client

### Requirement: TeammateBase 基类与上下文

系统 SHALL 提供 `chatbi.capabilities.teammates.base.TeammateBase` 抽象基类，子类必须实现 `async def call(payload, ctx)`，基类提供 `await self.raise_question(event)` 透传到 `ctx.ask_back`。`TeammateContext` 必须包含 `ask_back`、`logger`、`trace_metadata`、`plan_run_id` 字段。

#### Scenario: 子类未实现 call

- **WHEN** 实例化未实现 `call` 的子类
- **THEN** Python 抛 `TypeError`

#### Scenario: raise_question 透传

- **WHEN** Teammate 内部 `await self.raise_question(ev)`
- **THEN** 实际调用 `ctx.ask_back.raise_and_wait(ev)`

### Requirement: 临时拉起与销毁

系统 SHALL 通过 `TeammateFactory.spawn(name, ctx)` 在每次 Teammate 调用时构造实例；调用结束（成功 / 异常 / 取消）后必须释放实例与其持有的临时资源；本 change 不实现实例池或预热。

#### Scenario: 一次调用一个实例

- **WHEN** 同一 plan_run 中两次调用 `ask_data`
- **THEN** `spawn` 被调用两次，产生两个不同实例

### Requirement: 统一重试

系统 SHALL 通过 `tenacity` 对 Teammate 调用做统一重试，仅对 `httpx.NetworkError`、`httpx.TimeoutException`、HTTP 5xx 重试；最大重试次数默认 1，可由 `SKILL.md` 的 `max_retries` 字段覆盖；指数退避 `0.5 * 2^k`，封顶 5s；每次重试必须给 LangSmith span 添加 `retry_attempt` 标签。

#### Scenario: 4xx 不重试

- **WHEN** 旧服务返回 400
- **THEN** Teammate 调用立刻抛错，不重试

#### Scenario: 5xx 重试到上限

- **WHEN** `max_retries=2`，旧服务连续 3 次 502
- **THEN** 共发 3 次请求（首次 + 2 次重试）后抛 `TeammateCallError`
- **AND** LangSmith 中三次 span 分别标 `retry_attempt=0/1/2`

### Requirement: 反问事件模型

系统 SHALL 提供基类 `AskBackEvent`（pydantic）以及两个具象子类 `ChoiceAskBack`（`type=choice`，含 `options`、`multi_select`）和 `FillAskBack`（`type=fill`，含 `placeholder`、`validator`）；所有事件含 `event_id`、`teammate_id`、`slot`、`question`、`resume_strategy`（枚举 `slot_fill` / `replan`）、`type`。

#### Scenario: 序列化往返

- **WHEN** `ChoiceAskBack(...)` 经 `model_dump_json()` 后再 `model_validate_json`
- **THEN** 还原后 `type == "choice"` 且字段一致

### Requirement: AskBackHub 与队列

系统 SHALL 在每个 plan_run 提供一个 `AskBackHub` 实例（plan_run 级单例），内部维护 `AskBackQueue`（FIFO，上限 8）；`raise_and_wait(ev)` 入队并 `await` 一个 future；同一时刻 hub 只允许一个 event 处于"已 pop 待用户回答"状态。

#### Scenario: 串行 pop

- **WHEN** plan_run 内两个 Teammate 同时 `raise_and_wait`
- **THEN** Hub 一次只把队首事件推给中控
- **AND** 第二个 Teammate 阻塞，直到第一个被 resolve

#### Scenario: 队列满

- **WHEN** 已有 8 个未决事件，第 9 个 enqueue
- **THEN** 抛 `AskBackQueueFullError`

### Requirement: AskBackInterruptHandler 与续跑

系统 SHALL 实现 `AskBackInterruptHandler` 节点：从 Hub 取出当前事件，通过 LangGraph `interrupt()` 暂停图执行，把事件抛给会话层（出口由 `add-streaming-conversation` 实现）；提供 `resume(event_id, user_answer)` API：根据 `resume_strategy`：
- `slot_fill`：`future.set_result(user_answer)`，Teammate 续跑；
- `replan`：`future.set_result(user_answer)` + 设置 `plan_run.replan_needed=True`，下一节点回到规划。

#### Scenario: slot_fill 续跑

- **WHEN** Teammate 触发 `FillAskBack(resume_strategy="slot_fill")`，用户回答 "上自然月"
- **THEN** Teammate 内 `raise_question` 返回 "上自然月"
- **AND** plan_run 不进入 replan 分支

#### Scenario: replan 重规划

- **WHEN** Teammate 触发 `ChoiceAskBack(resume_strategy="replan", options=["A","B"])`，用户答 "A"
- **THEN** plan_run 标记 `replan_needed=True`
- **AND** 下一次 LangGraph step 进入规划节点，上下文包含 `用户最近答复："A"`

### Requirement: 反问超时

系统 SHALL 为每个未决反问设置 30 分钟超时，超时后 Hub 自动 `set_exception(AskBackTimeout)`，触发 plan_run 失败并清理队列。

#### Scenario: 用户半小时未答

- **WHEN** 30 分钟内 `resume` 未被调用
- **THEN** Teammate 的 `raise_question` 抛 `AskBackTimeout`
- **AND** plan_run 状态置为失败

### Requirement: raise_question 工具注入

系统 SHALL 在 deepagents 适配层为每个 `type=teammate` 的 subagent 自动注入 `raise_question` 工具，工具内部把参数构造为相应 `AskBackEvent` 子类并调 `ctx.ask_back.raise_and_wait`，返回用户回答字符串。

#### Scenario: subagent 调用工具

- **WHEN** subagent 内执行 `raise_question(slot="time", question="自然月还是财月?", type="choice", options=["自然月","财月"])`
- **THEN** 中控收到 `ChoiceAskBack(slot="time", options=["自然月","财月"])`

### Requirement: ask_data 示例 Teammate

系统 SHALL 在 `skills/teammates/ask_data/` 与 `chatbi/capabilities/teammates/ask_data/` 提供一个完整示例：mock 一个本地 HTTP 端点（pytest fixture 起 httpx mock 服务），演示成功调用、4xx、5xx 重试、反问 slot_fill 全流程。

#### Scenario: 成功调用

- **WHEN** 用例向 `ask_data` 提交 `{"question":"上月销量"}` 且 mock 服务返回 200 + 数据
- **THEN** Teammate 返回 `{"data": ...}` 且 LangSmith trace 含 1 个 span

#### Scenario: 反问后续跑

- **WHEN** 模拟 `ask_data` 内部触发一次 `slot_fill` 反问，并 resume("自然月")
- **THEN** Teammate 最终返回结果包含基于 "自然月" 的查询数据
