## Context

GeneralistAgent 当前是一个单 Agent 的中控骨架：`cli.py` 用同步 `agent.invoke()` 阻塞调用，LLM 生成完整后才一次性打印；项目目标是成为"供应链 ChatBI 中控 Agent"，需要调用问数 Agent 等已建设好的外部 Agent 服务，但缺少多 Agent 协作基础设施。

参考 Claude Code 的 Agent Teams 机制（同进程 Teammate + 共享 Task List + Mailbox 消息通道 + Runner idle 循环），本项目用 Python + asyncio 实现等价能力。现有架构：`config.py` / `model.py` / `agent.py`（DeepAgents）/ `skills/center.py`（SkillCenter 远程 SQLite 同步本地 SKILL.md）/ `interface/cli.py`。

关键约束：
- 外部已建设 Agent 服务（问数 Agent 等）零改造，仅通过 Teammate 代理调用其 API。
- 复用现有 SkillCenter 技能系统描述外部 Agent 能力。
- 同进程隔离（contextvars），代码运行沙箱后续单独处理。

## Goals / Non-Goals

**Goals:**
- CLI 改为真异步流式：`astream(stream_mode=["messages","updates"])` 逐 token 渲染，工具调用与节点更新可见。
- 流式结束后手动重建 `state["messages"]`，保持多轮上下文连续。
- 提供多 Agent 协作基础设施：Team / Teammate / Runner / Mailbox / Task List。
- Teammate 独立 LLM 实例，可指定不同 model/provider。
- 外部 Agent 服务通过 SKILL.md（能力描述）+ MCP（调用方式）双通道接入。
- 中控 Agent 可用团队编排工具（team_create / spawn_teammate / send_message / assign_task / task_list）。

**Non-Goals:**
- 代码执行沙箱隔离（后续 change 单独处理）。
- 子进程级 Teammate 隔离（本期仅同进程 contextvars）。
- Teammate 嵌套创建 Teammate（与 Claude Code 一致，扁平名册）。
- 跨机器分布式 Team（本期仅单进程内）。
- 现有 SkillCenter 行为变更（仅复用）。

## Decisions

### D1: 流式采用 `stream_mode=["messages","updates"]` 双模式
- **选择**：同时订阅 messages（token 级）+ updates（节点级）。
- **理由**：messages 提供 token 级流式体验；updates 提供节点边界（如"工具节点完成"），便于区分 AI 输出与工具返回。单 messages 模式拿不到工具返回的完整结构化结果。
- **替代方案**：单 `stream_mode="values"` —— 否决，非 token 级，用户等得久；结束后再 `ainvoke` 一次 —— 否决，重复调用浪费 token。

### D2: 流式后手动重建 state
- **选择**：流式期间累积所有 `AIMessageChunk`（合并为完整 AIMessage）+ 从 updates 收集 ToolMessage，结束后设置 `state["messages"] = 重建列表`。
- **理由**：astream 不直接返回最终 state；手动重建最干净，避免重复调用。
- **替代方案**：额外发一次 `ainvoke` 取最终 state —— 否决，重复消耗。

### D3: Teammate 同进程隔离用 contextvars
- **选择**：`contextvars.ContextVar` 持有当前 Teammate 身份（teammate_id / team_name / color），每个 Teammate 的 agent loop 在自己的 context 中运行。
- **理由**：轻量、零进程开销、Python 原生支持，与 Claude Code 的 teammateContext 等价。
- **替代方案**：subprocess 隔离 —— 否决，本期 Non-Goal，开销大且通信复杂。

### D4: Teammate 独立 LLM 实例
- **选择**：`spawn_teammate` 接收 `model_config`（provider/model/base_url/api_key），各自 `init_chat_model`。
- **理由**：不同外部 Agent 服务可能用不同模型（问数用便宜模型，总结用强模型）；与 Leader 解耦。
- **替代方案**：共享 Leader 的 model —— 否决，灵活性不足，违背"各 Agent 独立有自己的 LLM 实例"决策。

### D5: 外部 Agent 服务对接 —— SKILL 牵引 + Teammate 绑定异构访问工具
- **选择**：对接链路为 `Leader → spawn_teammate → Teammate → 外部服务`。SKILL.md 是 Teammate 模型的"操作手册"，描述该 Teammate 的能力与如何访问外部服务，注入 Teammate 的 system prompt 牵引模型使用哪些工具；访问工具（MCP 工具调用 或 非标准化网络请求）绑定在 Teammate 的工具集上，由 Teammate 通过 SKILL 牵引调用。
- **权限边界（精确版）**：被**显式认定为"需要代理 Teammate 对接"的外部 Agent 服务**——其访问工具不进 Leader 工具集，Leader 也不掌握其调用方式（仅通过 TaskList / SendMessage 间接感知此类 Teammate 的能力与产出）。这不是剥夺 Leader 访问所有外部服务的权限：Leader 仍可持有编排工具、DeepAgents 内置工具，以及它自己直接对接的简单服务工具；禁令仅针对"被认定为需要代理对接"的那一类外部 Agent 服务。
- **理由**：外部已建设服务异构——有的提供 MCP，有的仅有 REST API；Teammate 按需装配对应工具（MCP 或网络请求客户端），SKILL 统一认知层，访问方式保持异构灵活性。Leader 与"需代理对接"类外部服务解耦，只管派任务收结果，符合"统一通过代理 Teammate 对接"。
- **替代方案**：让 Leader 直接持有这类外部服务 MCP 工具 —— 否决，Leader 耦合该类服务细节、工具集膨胀，违背代理模式；仅 SKILL 不绑定工具 —— 否决，模型需自己拼 HTTP 请求，易错。

### D6: Teammate 通信用 Mailbox（asyncio.Queue）+ 共享 Task List（文件）
- **选择**：Mailbox 用 `asyncio.Queue` 进程内传递消息（替代 Claude Code 的 500ms 轮询文件）；Task List 用 JSON 文件持久化（`~/.generalist/tasks/{team}/`），与 Claude Code 一致可跨重启观察。
- **理由**：asyncio.Queue 比轮询高效且实时；Task List 用文件保留可观测性与 Claude Code 兼容心智。
- **替代方案**：全用文件 + 轮询 —— 否决，延迟高、CPU 浪费；全用内存 —— 否决，Task List 丢失可观测性。

### D7: Runner idle 循环驱动 Teammate
- **选择**：每个 Teammate 有一个 asyncio Task 作为 runner，循环：检查 Task List 可领任务 → 检查 Mailbox 消息 → 有则进入 agent loop → 无则 `asyncio.sleep` 等待 → 收到 shutdown 则退出。
- **理由**：与 Claude Code runner 等价，teammate 透明领任务，无需硬编码。
- **替代方案**：Leader 显式驱动 —— 否决，耦合 Leader，违背"teammate 自主领任务"。

### D8: 编排工具作为 DeepAgents 工具暴露给 Leader
- **选择**：`team_create` / `team_delete` / `spawn_teammate` / `send_message` / `assign_task` / `task_list` 包装为 LangChain Tool，在 `build_agent` 中注册。
- **理由**：Leader 通过自然语言决策何时组建团队、分配任务，符合 Agent 范式。
- **替代方案**：硬编码编排逻辑 —— 否决，灵活性差。

### D9: Mailbox 作为 Teammate 完成回调，替代 Leader 对 task_list_query 的忙等
- **选择**：Runner 在 `_run_one_turn` 处理完任务或消息后，主动通过 Mailbox 给 Leader 投递结构化通知（`kind="task_completed" / "task_failed" / "message_reply"`，meta 携带 task_id / teammate_name / reason），Leader 通过新增 `wait_for_message(timeout)` 工具阻塞挂起信箱直到消息到达或超时；TaskList 退回工作池与依赖关系的角色，不再承担"通知 Leader"职责。
- **理由**：现状是 Leader 在 DeepAgents 的 LLM 推理循环里反复调 `task_list_query` 做忙等，每次轮询都消耗一次 LLM 推理，浪费 token 且引入延迟。让 Runner 主动回调匹配 Claude Code 的 subagent idle notification 心智，Leader 在等待期间不占 LLM 推理；同时让 Teammate 不再依赖"模型记得 SendMessage"才能回信，更鲁棒。
- **替代方案**：把 TaskList 也做成可订阅的事件通道 —— 否决，重复造轮子且不需要持久化的"事件"语义；Leader 端用代码层 sleep+poll —— 否决，仍占 LLM 推理一次。

### D10: 外部服务通信全程日志 + 日志分层前缀
- **选择**：
  1. 代理工具（特别是 NL2SQL SSE）在 **请求发出 / 每个 SSE 事件 / 最终结果 / 任何失败** 都打印一条带 `[NL2SQL]` 前缀的日志（`🡒 / 🡐 / ✓ / ✗`）。
  2. HTTP 工具的连接超时与读取超时分层：连接 10s 快失败，SSE 读取不限，由 Runner 总超时兜底。
  3. 全局新增 `src/interface/log.py` 提供 `leader_log / teammate_log / nl2sql_log / orchestrator_log / mailbox_log` 等带前缀+ANSI 颜色的辅助函数，自动检测终端是否支持彩色（不支持则降级为纯文本）。
- **理由**：当前现象是"Teammate 痕迹 + Leader 流式 + 工具返回 JSON"三路混杂在终端不可读，且 NL2SQL 连接失败时工具会沉默等待至 Runner 超时（默认 120s）才暴露问题；分层日志能让人在终端一眼看出每条来自哪一层，连接失败立即可见。
- **替代方案**：用 loguru 或 logging 写文件 —— 否决（互动 REPL 场景人还是要看终端）；只加前缀不分色 —— 否决，前缀字符串相近时还是难分。

## Risks / Trade-offs

- **[异步改造影响面大]** → `repl` 全异步化，`main.py` 入口变。缓解：保留同步 `print_stream` 逻辑复用，渐进迁移；充分集成测试覆盖多轮上下文。
- **[手动重建 state 可能遗漏消息类型]** → 工具调用链复杂时（多轮 tool_calls）可能漏 ToolMessage。缓解：从 updates 的 tool 节点完整收集 ToolMessage，单测覆盖多工具场景。
- **[同进程 Teammate 阻塞事件循环]** → 某个 Teammate 的 LLM 调用若同步阻塞会卡住整个 loop。缓解：所有 Teammate 调用走 `astream`/`ainvoke`，禁止同步 LLM 调用。
- **[MCP 外部服务可用性]** → 外部 Agent 服务宕机时 Teammate 卡死。缓解：MCP 调用加超时与重试，超时返回错误消息给 Leader。
- **[Team 资源泄漏]** → Leader 忘记 `team_delete` 导致 asyncio Task 与文件残留。缓解：进程退出时清理钩子 + `team_list` 工具可查活跃团队。
- **[Token 流式渲染与工具调用交错混乱]** → 用户难以分辨 token 属于哪次工具调用。缓解：updates 节点边界处打印分隔符与节点名。

## Migration Plan

1. **阶段一（流式）**：先改 `cli.py` + `main.py` 为异步流式，确保现有单 Agent 功能不回归（测试通过）。
2. **阶段二（基础设施）**：实现 `src/orchestration/` 各模块 + 单元测试，暂不接入 Leader。
3. **阶段三（编排工具）**：实现工具并注册进 `build_agent`，端到端验证"问数"场景。
4. **回滚**：各阶段独立，流式阶段可单独回滚到 `invoke`；编排模块为新增，回滚即删除 `src/orchestration/`。

## Open Questions

- 外部 Agent 服务的 MCP 配置具体格式（地址、认证方式）需在接入真实问数 Agent 时确定，本期先用 mock 服务验证流程。
- Teammate 数量上限与并发调度策略（是否需要限流）待真实压测后定。
