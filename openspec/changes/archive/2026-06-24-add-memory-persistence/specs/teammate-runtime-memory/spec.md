## ADDED Requirements

### Requirement: Teammate 在请求内累积记忆
同一 `Teammate.Runner` 在一次用户请求内被多次唤起（多次 `assign_task` / `send_message`）时 SHALL 共享同一份 LangGraph state（同一 `MemorySaver` + 同一 `thread_id`），上一次的工具调用结果、消息内容 SHALL 对下一次唤起可见。

#### Scenario: 同一 Teammate 多次任务记得前情
- **WHEN** Leader 给 Teammate A 派任务 "查 Q1 销售"，再派 "上一步结果按地区拆开"
- **THEN** Teammate A 在第二个任务里 SHALL 无需 Leader 重发 Q1 销售上下文即可继续

#### Scenario: 不同 Teammate 互不可见
- **WHEN** Leader 同时建 Teammate A 与 Teammate B，给 A 派任务后给 B 派
- **THEN** B SHALL 看不到 A 的对话历史（各自独立 MemorySaver）

### Requirement: Runner 只构建 Agent 一次
`Runner` SHALL 在 idle 循环首次启动时调用一次 `Teammate.build_agent_for_prompt()` 并缓存，后续每轮 `_run_one_turn` SHALL **不**重新构建 Agent；SKILL 内容在 spawn 那一刻即冻结。

#### Scenario: 不再每 turn 重建
- **WHEN** Runner 处理一个请求内的第 N 次唤起
- **THEN** SHALL 复用 self._agent，不调用 build_agent_for_prompt

#### Scenario: SKILL 冻结
- **WHEN** Teammate 启动后用户手动修改其 SKILL.md
- **THEN** Teammate 当前请求 SHALL 仍使用启动时的 SKILL 内容（Leader 仍然 SHALL 感知 SKILL 热更新）

### Requirement: 请求结束焚毁本轮新建 Teammate
Leader 每轮用户请求结束时，CLI SHALL 调用 `team_manager.cleanup_spawned_in_turn()`，对本轮 `spawn_teammate` 创建的所有 Teammate 发起 `shutdown_request` 并等待 Runner 退出；之后下一轮请求 SHALL **不**复用上一轮的 Teammate 实例。

#### Scenario: 一轮结束清空
- **WHEN** Leader 在本轮 spawn 了 Teammate A 与 B 并完成回复
- **THEN** 轮次结束后 `team_manager.list_teammates(team)` SHALL 不包含 A 与 B；A、B 的 Runner.task 状态 SHALL 为 done

#### Scenario: 下一轮新建同名 Teammate
- **WHEN** 上一轮的 Teammate A 已焚毁，下一轮 Leader 又 `spawn_teammate(name="A")`
- **THEN** SHALL 创建全新实例，记忆从零开始

#### Scenario: cleanup 异常不阻塞 REPL
- **WHEN** cleanup_spawned_in_turn 过程中某个 Runner 抛异常
- **THEN** CLI SHALL 打印告警但继续接收下一轮用户输入

### Requirement: Teammate 仅使用 MemorySaver
Teammate 端 SHALL **仅**使用 `MemorySaver`，**不得**写入 `memory/leader.db` 或任何持久化存储；Teammate 的对话历史 SHALL 在请求结束时与 Runner 一同被 Python GC 回收。

#### Scenario: 不污染 leader.db
- **WHEN** Teammate 完成多次内部推理
- **THEN** `memory/leader.db` 的 checkpoint SHALL **不**包含任何 `thread_id` 等于 Teammate 的 teammate_id 的记录
