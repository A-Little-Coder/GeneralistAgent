## ADDED Requirements

### Requirement: 反问中断推送

系统 SHALL 在 `AskBackHub` 触发反问时，由 `EventNormalizer` 推送一个 `ask_back` 事件，含 `event_id`、`type`（`choice`/`fill`）、`question`、`slot`、`resume_strategy`、对应表单字段（`options`/`multi_select`/`placeholder`/`validator`）；推送后 SSE 流挂起等待续跑。

#### Scenario: 反问推送

- **WHEN** plan_run 中触发 `ChoiceAskBack`
- **THEN** SSE 流推送一个 `ask_back` 事件
- **AND** 流不立即关闭，持续保持

### Requirement: 续跑接口

系统 SHALL 提供 `POST /api/chat/resume`，请求体 `{plan_run_id, event_id, answer}`，行为：① 调 `AskBackHub.resume(event_id, answer)`；② 若原 SSE 流仍连接，事件继续推送；③ 若 SSE 已断开，重新建立新 SSE 流并从 checkpoint 恢复。

#### Scenario: 在线续跑

- **WHEN** 客户端原 SSE 还连接，POST 给 resume
- **THEN** 原 SSE 在 1 秒内继续推送事件

#### Scenario: 离线续跑

- **WHEN** 原 SSE 已断开
- **THEN** resume 接口本身返回新的 SSE 流（同 schema），从中断节点恢复

### Requirement: replan 续跑

系统 SHALL 当反问 `resume_strategy=replan` 时把答案附加到对话上下文，让 LangGraph 回到 `plan` 节点重新规划；最终用户应得到根据新答案规划后的回答。

#### Scenario: replan 流程

- **WHEN** 用户回答触发 replan 后
- **THEN** 后续事件中再次出现 `node_enter:plan`
- **AND** 最终 `final` 事件给出新规划下的回答

### Requirement: Checkpoint 持久化

系统 SHALL 使用 LangGraph `Checkpointer`（基于 `add-memory-persistence` 的 SQLite/Redis 后端）在每个节点结束后持久化 LangGraph state，`plan_run_id` 作为 thread_id；TTL 30 分钟与 BlackboardStore 一致。

#### Scenario: 中断后恢复

- **WHEN** 反问中断后服务重启
- **THEN** 通过 `plan_run_id` 调 resume 仍能从中断点继续