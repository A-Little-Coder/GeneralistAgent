## Why

历史上已建设的散点 Agent（问数、预测、归因、报告生成等）需要被统一以"Teammate Agent + 套壳 SKILL/MCP"方式接入中控；接入方式必须可复用，否则每接一个 Agent 都要重写一次胶水代码。同时所有 Teammate 在执行中可能需要向用户反问以澄清入参或方向，反问能力必须做成通用组件，由 Teammate 透传到中控统一出口（只有中控能直接和用户说话）。

## What Changes

- 定义 Teammate 接入协议：每个旧 Agent 套壳为一个目录在 `skills/teammates/<name>/`，包含 `SKILL.md` + `client.py`（HTTP / MCP 调用）+ `prompts/system.md`
- 实现 Teammate 临时拉起机制：每次任务 per-turn 实例化，调用结束销毁；不做预热池
- 实现统一重试：默认 1 次，可在 `SKILL.md` 的 `max_retries` 字段 override，每次重试在 LangSmith 标 `retry_attempt=k`
- 实现反问通用组件：
  - `raise_question(payload)`：Teammate 侧触发工具，注入到每个 Teammate 的工具集
  - `AskBackInterruptHandler`：中控 LangGraph 节点级中断处理器
  - `AskBackQueue`：FIFO 队列，同一时刻只 pop 一个未决反问推前端
- 定义反问类型二分：`slot_fill`（续跑，不重规划）/ `replan`（丢弃当前 plan，回到规划节点）
- 定义反问形式两类模板：`ChoiceAskBack`（选择，含 options / multi_select）/ `FillAskBack`（填空，含 placeholder / validator）
- 提供 1 个示例 Teammate（`ask_data` 问数）作为参考实现与单元测试样板
- 中控的反问出口与会话层 SSE 对齐（不在本 change 实现 SSE，但定义协议）

## Capabilities

### New Capabilities

- `teammate-protocol`: Teammate 套壳接入协议、临时拉起、统一重试
- `ask-back`: 反问通用组件（队列、二分类型、选择/填空模板）

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/capabilities/teammates/`（基类 + ask_data 示例）、`chatbi/infra/ask_back/`
- 影响依赖：新增 `httpx`、`tenacity`（重试）
- 影响目录：新增 `skills/teammates/ask_data/` 完整示例
- 依赖前置：`add-chatbi-foundation`、`add-skill-registry`
- 被依赖：`add-orchestrator-planner` 在执行节点调用 Teammate；`add-streaming-conversation` 在 SSE 端消费反问事件
