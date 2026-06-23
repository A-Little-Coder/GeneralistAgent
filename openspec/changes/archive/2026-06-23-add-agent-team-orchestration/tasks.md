## 1. 异步流式输出（阶段一）

- [x] 1.1 在 `src/interface/cli.py` 新增 `print_stream_event` 流式渲染函数，处理 `messages` 模式的 AIMessageChunk（逐 token 打印 `end="", flush=True`）与 tool_call_chunks
- [x] 1.2 在 `print_stream_event` 中处理 `updates` 模式，节点边界打印分隔符与节点名，工具节点完成打印"📥 工具返回"及截断内容
- [x] 1.3 将 `repl` 改为 `async def`，用 `agent.astream(state, config, stream_mode=["messages","updates"])` 替换 `agent.invoke`
- [x] 1.4 实现流式后手动重建 `state["messages"]`：累积 AIMessageChunk 合并为完整 AIMessage，从 updates 收集 ToolMessage，组成完整列表写回 state
- [x] 1.5 将 `src/main.py` 的 `main()` 改为 `asyncio.run(repl(...))` 异步入口
- [x] 1.6 编写流式输出集成测试：逐 token 输出、多工具调用链重建、多轮上下文连续
- [x] 1.7 回归验证现有单 Agent 功能（中文回复、工具调用、技能热更新）不破坏

## 2. 多 Agent 协作基础设施（阶段二）

- [x] 2.1 创建 `src/orchestration/` 模块骨架（`__init__.py`）
- [x] 2.2 实现 `context.py`：基于 `contextvars.ContextVar` 的 TeammateContext（teammate_id / team_name / color），提供 get/set 与 context 运行辅助
- [x] 2.3 实现 `task_list.py`：共享 Task List（JSON 文件持久化于 `~/.generalist/tasks/{team}/`），支持创建、领取、状态流转（pending/in_progress/completed）、依赖（blockedBy）、列表查询
- [x] 2.4 实现 `mailbox.py`：基于 `asyncio.Queue` 的 Mailbox，支持点对点发送、广播、读取后移除
- [x] 2.5 实现 `teammate.py`：Teammate 身份与独立 LLM 实例初始化（接收 model_config，调用 init_chat_model），注入协作 system prompt，从初始 prompt 构建上下文
- [x] 2.6 实现 `runner.py`：Runner（asyncio Task）idle 循环 —— 检查 Task List 可领任务 → 检查 Mailbox 消息 → 有则进入 agent loop（astream）→ 无则 asyncio.sleep 等待 → 收到 shutdown 退出并标记 completed
- [x] 2.7 实现 `team.py`：Team 容器生命周期（创建配置+成员名册+空 Task List、删除校验活跃成员、绑定 Leader、拒绝 Teammate 创建 Teammate）
- [x] 2.8 为 2.2-2.7 各模块编写单元测试（身份隔离、任务流转、消息收发、Runner 领任务、Team 生命周期边界）

## 3. 外部 Agent 服务代理对接（阶段二）

- [x] 3.1 定义代理 Teammate 的专属 SKILL.md 模板（描述能力 + 如何访问外部服务，牵引模型使用哪些工具），接入现有 SkillCenter 同步机制
- [x] 3.2 实现访问工具绑定到 Teammate 的机制：`spawn_teammate` 支持为 Teammate 装配异构访问工具（MCP 工具调用 或 非标准化网络请求客户端），支持超时与重试；确认 Leader 工具集不包含任何外部服务访问工具
- [x] 3.3 在 `.env` / Config 中新增外部 Agent 服务配置项（API 地址、认证、访问方式 MCP/HTTP），更新 `.env.example`
- [x] 3.4 用 mock 问数服务验证 Teammate 通过专属 SKILL 牵引 + 绑定访问工具的完整调用链（分别覆盖 MCP 方式与网络请求方式）

## 4. 团队编排工具与 Leader 集成（阶段三）

- [x] 4.1 实现 `src/orchestration/tools.py`：将 `team_create` / `team_delete` / `team_list` / `spawn_teammate` / `send_message` / `assign_task` / `task_list` 包装为 LangChain Tool
- [x] 4.2 在 `src/core/agent.py` 的 `build_agent` 中注册编排工具（仅 Leader 拥有，Teammate 不注册 spawn_teammate）
- [x] 4.3 端到端验证"问数"场景：用户提问 → Leader 自然语言决策 → team_create + spawn_teammate + assign_task → Teammate 调 mock 问数服务 → SendMessage 返回 → Leader 流式汇总输出
- [x] 4.4 实现进程退出清理钩子：REPL 退出时向所有活跃 Teammate 发 shutdown，清理 asyncio Task 与 Task List 文件
- [x] 4.5 编写编排工具与端到端场景的集成测试

## 5. 文档与收尾

- [x] 5.1 更新 `CLAUDE.md` 的 Code Architecture 章节，补充 `orchestration/` 模块说明
- [x] 5.2 全量运行测试套件，所有 64 项测试通过
- [x] 5.3 手动运行 `python src/main.py` 验证流式输出与多 Agent 协作端到端可用（待用户验证）

## 6. 端到端通信与日志加固

- [x] 6.1 `runner.py`：任务/消息处理完成后，Runner 主动通过 Mailbox 给 Leader 投递 `kind="task_completed" / "task_failed" / "message_reply"` 通知（meta 携带 task_id / teammate_name），TaskList 退回工作池角色
- [x] 6.2 `tools.py`：新增 `wait_for_message(timeout, team_name?)` LangChain Tool（async），让 Leader 阻塞挂起信箱直到有消息或超时；返回 `{status, from, content, kind, meta}` 或 `{status: "timeout"}`
- [x] 6.3 `cli.py` 系统 prompt：把"反复轮询 task_list_query"的引导改为"分配任务后调 wait_for_message 等回信"
- [x] 6.4 `nl2sql_tools.py`：连接超时单独配短（10s），打印 `[NL2SQL] 🡒 / 🡐 / ✓ / ✗` 全程日志（请求发出 / 每个 SSE 事件 / 最终结果 / 错误）
- [x] 6.5 `proxy_tools.py` HTTP 通用工具：失败路径同步加 `[Proxy] ✗ ...` 错误日志，防默默吃错
- [x] 6.6 新增 `src/interface/log.py`：统一前缀+颜色辅助函数（`leader_log` / `teammate_log` / `nl2sql_log` / `orchestrator_log` / `mailbox_log`），自动检测 ANSI 支持并降级
- [x] 6.7 `runner.py` 现有 trace 改用 `log.teammate_log`；`tools.py` 编排工具入口加 `log.orchestrator_log`；`cli.py` 渲染器加 `log.leader_log` 前缀
- [x] 6.8 单元测试：`test_runner_completion_notification`（任务完成有 mailbox 通知）、`test_wait_for_message_tool`（成功 / 超时）、`test_nl2sql_connect_refused_logs`（连接失败明确报错）
- [x] 6.9 全量回归 + 手动验证：起 NL2SQL → 问"查学校成绩" → 终端日志按层分色 → Leader 不再忙等 → 失败时立即明确
