## ADDED Requirements

### Requirement: AskBackEvent 模型库

系统 SHALL 在 `chatbi.infra.ask_back.events` 暴露 `AskBackEvent` 基类与 `ChoiceAskBack`、`FillAskBack` 两个 pydantic 子类，模型字段满足 `add-teammate-protocol` spec 中的描述；模型必须可 JSON 序列化往返。

#### Scenario: 子类正确判别

- **WHEN** 给定 JSON `{"type":"choice","options":["a","b"],...}`
- **THEN** `AskBackEvent.model_validate_json(...)` 实际生成 `ChoiceAskBack` 实例

### Requirement: AskBackHub API

系统 SHALL 在 `chatbi.infra.ask_back.hub` 提供 `AskBackHub` 类，公开方法：`raise_and_wait(event) -> str`、`resume(event_id, answer)`、`fail(event_id, exc)`、`current() -> AskBackEvent | None`、`pending_count() -> int`；线程/协程安全。

#### Scenario: pending_count 反映队列长度

- **WHEN** 同时入队 3 个事件，未 resume
- **THEN** `hub.pending_count() == 3`

### Requirement: 中断处理器与 LangGraph 集成

系统 SHALL 提供 `AskBackInterruptHandler` 节点函数（`async def`，符合 LangGraph 节点签名），其行为：①若 `hub.current()` 非空则 `interrupt()`；②否则透传至下一节点；③暴露统一事件出口（dependency injection 由会话层注入）。

#### Scenario: 无未决事件不中断

- **WHEN** `hub.current() is None`
- **THEN** handler 不调用 `interrupt()`

### Requirement: 反问工具

系统 SHALL 提供 LangChain `BaseTool` 实现 `raise_question`，名称在工厂方法 `make_raise_question_tool(ask_back)` 中绑定到具体 hub；工具入参 schema：`slot: str, question: str, type: Literal["choice","fill"], resume_strategy: Literal["slot_fill","replan"]="slot_fill", options: list[str] | None = None, multi_select: bool = False, placeholder: str | None = None, validator: str | None = None`。

#### Scenario: type=choice 时缺 options

- **WHEN** subagent 调用 `raise_question(type="choice", ...)` 但未传 options
- **THEN** 工具抛 `ValidationError`，subagent 收到错误信息可重试
