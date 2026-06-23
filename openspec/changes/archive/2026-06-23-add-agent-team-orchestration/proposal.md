## Why

当前 CLI 使用 `agent.invoke()` 阻塞式调用，所有输出在 LLM 完整生成后才一次性打印，用户只能干等，体验差且无法看到生成过程。同时项目定位为"中控 Agent"，需要调用问数 Agent 等已建设好的外部 Agent 服务，但目前没有任何多 Agent 协作的基础设施 —— 无法统一编排、无法让子 Agent 领取任务、无法在 Agent 间通信。现在需要把这两块一起补齐：流式是异步化的前置依赖，多 Agent 通信本身也需要流式输出能力。

## What Changes

- **CLI 改为真异步流式输出**：`repl` 改用 `asyncio` 驱动，调用 `agent.astream(stream_mode=["messages","updates"])`，逐 token 打印 LLM 输出，同时展示工具调用与节点更新；流式结束后手动重建完整 `state["messages"]` 以保持多轮上下文连续。**BREAKING**：`repl` 由同步函数改为 `async def`，`main.py` 需用 `asyncio.run()` 启动。
- **新增多 Agent 协作基础设施层** `src/orchestration/`，参考 Claude Code Agent Teams 机制，包含 Team 容器、Teammate（同进程隔离）、Runner（idle 循环自动领任务）、Mailbox（消息通道）、共享 Task List。
- **Teammate 独立 LLM 实例**：每个 Teammate 可指定自己的 model/provider 配置，不与 Leader 共享。
- **外部 Agent 服务统一代理对接**：被认定为"需代理对接"的外部 Agent 服务（如问数 Agent）统一通过代理 Teammate 对接；Teammate 持有专属 SKILL（牵引模型如何访问）+ 异构访问工具（MCP 或非标准化网络请求，绑定在 Teammate 上）。该类外部服务的访问工具不进 Leader 工具集，Leader 不掌握其调用方式（仅通过 TaskList/SendMessage 间接感知）；Leader 保留编排工具、内置工具及自己直接对接的简单服务工具。外部服务零改造。
- **新增中控 Agent 可用的团队编排工具**：`team_create` / `team_delete` / `spawn_teammate` / `send_message` / `assign_task` / `task_list`，作为 DeepAgents 工具暴露给 Leader。

## Capabilities

### New Capabilities
- `agent-team-orchestration`: 多 Agent 协作基础设施，包含 Team 容器生命周期、Teammate 同进程隔离、Runner idle 循环、Mailbox 消息通道、共享 Task List、外部 Agent 服务代理对接（Teammate 专属 SKILL 牵引 + 异构访问工具绑定 Teammate，Leader 不直接调外部服务）。
- `streaming-output`: 异步流式输出能力，CLI 通过 `astream` 逐 token 渲染并手动重建对话状态。

### Modified Capabilities
- `deep-agent-demo`: 交互界面要求变更 —— 由"阻塞式调用后一次性打印"改为"真异步流式逐 token 输出"；多轮对话上下文维护方式由"直接接收 invoke 返回的 state"改为"流式期间手动重建 messages"。

## Impact

- **代码**：
  - `src/interface/cli.py` —— 重写 `repl` 为 async，新增 `print_stream_event` 流式渲染逻辑，手动重建 state。
  - `src/main.py` —— `main()` 改为 async 入口，`asyncio.run(repl(...))`。
  - 新增 `src/orchestration/` 模块（team / teammate / runner / mailbox / task_list / context）。
  - 新增 `src/orchestration/tools.py` —— 中控 Agent 团队编排工具，集成进 `build_agent`。
  - `src/core/agent.py` —— 注册编排工具。
- **依赖**：无新增第三方包（asyncio 为标准库，MCP 复用 LangChain 已有能力）。
- **配置**：`.env` 可能新增外部 Agent 服务的 MCP 配置项（如问数 Agent API 地址）。
- **测试**：新增 orchestration 各模块单元测试 + 流式输出集成测试；现有 `test_skill_center.py` 不受影响。
- **兼容性**：外部已建设 Agent 服务（如问数 Agent）零改造，仅通过 Teammate 代理调用其 API。
