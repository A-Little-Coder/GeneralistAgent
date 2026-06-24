## ADDED Requirements

### Requirement: 异步流式输出
CLI SHALL 使用 asyncio 驱动，通过 `agent.astream(stream_mode=["messages","updates"])` 逐 token 渲染 LLM 输出，而非阻塞等待完整结果后一次性打印。

#### Scenario: 逐 token 输出
- **WHEN** 用户提交一个请求，LLM 开始生成回复
- **THEN** 控制台 SHALL 在每个 token 到达时即时打印（`end="", flush=True`），用户能看到文字逐步出现，而非等待全部生成完毕

#### Scenario: 工具调用流式可见
- **WHEN** LLM 决定调用工具，通过 `tool_call_chunks` 流式产生工具调用
- **THEN** 控制台 SHALL 在工具名确定时打印"🛠 调用工具: <name>"，工具参数流式拼接时可见

#### Scenario: 节点更新可见
- **WHEN** `updates` 模式产生节点级更新（如工具节点完成）
- **THEN** 控制台 SHALL 在节点边界打印分隔符与节点名，清晰区分 AI 输出段与工具返回段

#### Scenario: 工具返回展示
- **WHEN** 工具节点完成并产生 ToolMessage
- **THEN** 控制台 SHALL 打印"📥 工具返回:"及截断后的返回内容

### Requirement: 异步入口
程序 SHALL 通过 `asyncio.run()` 启动异步 REPL 主循环。

#### Scenario: 异步启动
- **WHEN** 执行 `python src/main.py`
- **THEN** `main()` SHALL 用 `asyncio.run(repl(...))` 启动，`repl` 为 `async def`

#### Scenario: 输入与流式不互相阻塞
- **WHEN** 一个 Teammate 正在流式生成时（多 Agent 场景）
- **THEN** asyncio 事件循环 SHALL 允许其他协程（如 Leader 处理其他消息）并发执行，不被单个 LLM 调用阻塞

#### Scenario: 退出前清理本轮 Teammate
- **WHEN** REPL 主循环每轮结束（包括正常完成、Ctrl+C、异常）
- **THEN** SHALL 调用 `team_manager.cleanup_spawned_in_turn()`，本轮新建的 Teammate Runner 全部 shutdown 完毕后再读取下一行输入
