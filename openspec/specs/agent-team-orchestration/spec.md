## ADDED Requirements

### Requirement: Team 容器生命周期
系统 SHALL 提供 Team 容器作为多 Agent 协作的组织单元，包含成员名册、共享 Task List 与团队配置，并管理其创建与清理。

#### Scenario: 创建团队
- **WHEN** Leader 调用 `team_create(name)`
- **THEN** 系统 SHALL 创建团队配置（成员名册）、准备空的共享 Task List 目录，并将 Leader 绑定到该团队

#### Scenario: 删除团队
- **WHEN** Leader 调用 `team_delete(name)` 且团队中无活跃 Teammate
- **THEN** 系统 SHALL 清理团队配置与 Task List 目录

#### Scenario: 删除仍有活跃成员的团队
- **WHEN** Leader 调用 `team_delete(name)` 但团队中仍有运行中的 Teammate
- **THEN** 系统 SHALL 拒绝删除并提示先关闭活跃 Teammate

#### Scenario: 团队名册扁平
- **WHEN** 一个 Teammate 尝试调用 `spawn_teammate` 创建新的 Teammate
- **THEN** 系统 SHALL 拒绝（Teammate 不能创建 Teammate），仅 Leader 可创建 Teammate

### Requirement: Teammate 同进程隔离
系统 SHALL 在同一进程内通过 contextvars 隔离多个 Teammate 的身份与运行上下文，每个 Teammate 拥有独立的 agent loop 与身份（teammate_id / team_name / color）。

#### Scenario: 身份隔离
- **WHEN** 多个 Teammate 同时运行并各自调用获取当前身份的接口
- **THEN** 每个 Teammate SHALL 拿到自己的 teammate_id，互不混淆

#### Scenario: 独立 agent loop
- **WHEN** Teammate 启动
- **THEN** 系统 SHALL 在其专属 contextvars context 中运行完整的 agent loop，不继承 Leader 的完整对话历史，从自身初始 prompt 构建上下文

#### Scenario: 注入协作 system prompt
- **WHEN** Teammate 启动
- **THEN** 其 system prompt SHALL 被注入团队协作指令（说明通过 Task List 与 SendMessage 协调工作）

### Requirement: Teammate 独立 LLM 实例
每个 Teammate SHALL 拥有独立的 LLM 实例，可在创建时指定不同的 model / provider / base_url / api_key，不与 Leader 共享。

#### Scenario: 指定独立模型
- **WHEN** Leader 调用 `spawn_teammate(name, model_config)` 且 model_config 指定了不同的 model
- **THEN** 系统 SHALL 为该 Teammate 初始化独立的 LLM 实例，使用指定配置

#### Scenario: 默认继承配置
- **WHEN** Leader 调用 `spawn_teammate` 未提供 model_config
- **THEN** 系统 SHALL 使用默认 LLM 配置初始化该 Teammate 的独立实例

### Requirement: Runner idle 循环自动领任务
每个 Teammate SHALL 由一个 Runner（asyncio Task）驱动，循环检查共享 Task List 与 Mailbox：有可领任务或消息则进入 agent loop，无则等待，收到 shutdown 则退出。

#### Scenario: 自动领取待领任务
- **WHEN** Task List 中出现满足条件的任务（pending、无人负责、前置依赖已完成）
- **THEN** Teammate 的 Runner SHALL 自动领取该任务，将任务内容作为新 prompt 交给 agent loop 执行

#### Scenario: 无任务时进入等待
- **WHEN** Task List 无可领任务且 Mailbox 无消息
- **THEN** Runner SHALL 进入等待（asyncio.sleep 轮询），不消耗 LLM 调用

#### Scenario: 收到 shutdown 优雅退出
- **WHEN** Leader 通过 SendMessage 发送 shutdown_request
- **THEN** Runner SHALL 让 Teammate 处理收尾后退出循环，标记 task 为 completed 并发送终止事件

### Requirement: Mailbox 消息通道
系统 SHALL 为每个 Teammate 提供 Mailbox（asyncio.Queue）作为消息通道，支持点对点与广播通信，消息被读取后从队列移除。

#### Scenario: 点对点发送
- **WHEN** 一个 Agent 调用 `send_message(to="teammate-name", message)`
- **THEN** 消息 SHALL 写入目标 Teammate 的 Mailbox，目标 Runner 在下一轮 idle 检查时读取并转为新 prompt

#### Scenario: 广播
- **WHEN** 一个 Agent 调用 `send_message(to="*", message)`
- **THEN** 消息 SHALL 写入团队所有 Teammate 的 Mailbox

#### Scenario: 消息读取后移除
- **WHEN** Runner 从 Mailbox 读取一条消息
- **THEN** 该消息 SHALL 从队列中移除，不重复处理

### Requirement: 共享 Task List
系统 SHALL 提供团队共享的 Task List（JSON 文件持久化于 `~/.generalist/tasks/{team}/`），记录任务的状态、负责人与依赖关系，供所有成员读写。

#### Scenario: 创建任务
- **WHEN** Leader 调用 `assign_task(to, description)`
- **THEN** 系统 SHALL 在 Task List 创建一条 pending 任务，记录描述与负责人

#### Scenario: 查看任务状态
- **WHEN** Agent 调用 `task_list(team)`
- **THEN** 系统 SHALL 返回该团队所有任务及其当前状态（pending / in_progress / completed）

#### Scenario: 任务状态流转
- **WHEN** Teammate 领取任务、执行中、执行完成
- **THEN** Task List SHALL 分别更新为 in_progress、completed，反映真实进度

#### Scenario: 任务依赖
- **WHEN** 一个任务声明了前置依赖（blockedBy）且依赖未完成
- **THEN** Runner SHALL 不领取该任务，直到前置任务完成

### Requirement: 外部 Agent 服务代理对接
系统 SHALL 统一通过代理 Teammate Agent 对接被认定为"需代理对接"的外部 Agent 服务：Teammate 持有专属 SKILL（牵引模型如何访问）与异构访问工具（MCP 工具调用或非标准化网络请求，绑定在 Teammate 上）。该类外部服务的访问工具不进 Leader 工具集，Leader 不掌握其调用方式（仅通过 TaskList / SendMessage 间接感知此类 Teammate 的能力与产出），外部服务零改造。

#### Scenario: 专属 SKILL 牵引访问
- **WHEN** 为问数 Agent 创建代理 Teammate
- **THEN** 该 Teammate SHALL 持有专属 SKILL.md，描述其能力与如何访问外部服务，注入 Teammate 的 system prompt 牵引模型使用对应工具

#### Scenario: 访问工具绑定 Teammate 且 Leader 不持有
- **WHEN** 一个外部 Agent 服务被认定为"需代理对接"
- **THEN** 其访问工具 SHALL 绑定在对应 Teammate 工具集上由 SKILL 牵引调用，且 SHALL 不出现在 Leader 工具集中；Leader SHALL 不掌握该服务的调用方式

#### Scenario: Leader 保留其他工具权限
- **WHEN** 配置 Leader 工具集
- **THEN** Leader SHALL 保留编排工具、DeepAgents 内置工具及它自己直接对接的简单服务工具；禁令仅针对"被认定为需代理对接"的外部 Agent 服务访问工具

#### Scenario: MCP 方式访问
- **WHEN** 外部服务提供 MCP 协议
- **THEN** Teammate SHALL 装配 MCP 工具并通过其访问外部服务

#### Scenario: 非标准化网络请求访问
- **WHEN** 外部服务仅提供 REST API 等非标准化接口
- **THEN** Teammate SHALL 装配对应的网络请求工具访问外部服务

#### Scenario: 外部服务零改造
- **WHEN** 接入一个已有的问数 Agent 服务
- **THEN** 该外部服务 SHALL 无需任何代码改动，Teammate 仅作为其代理调用其接口

### Requirement: 团队编排工具暴露给 Leader
系统 SHALL 将团队编排能力包装为 LangChain 工具注册进 Leader 的 Agent，供 Leader 通过自然语言决策使用。

#### Scenario: 工具可用
- **WHEN** Leader 的 Agent 构建完成
- **THEN** SHALL 注册 `team_create` / `team_delete` / `spawn_teammate` / `send_message` / `assign_task` / `task_list` 工具

#### Scenario: 自然语言驱动编排
- **WHEN** 用户对 Leader 说"帮我查上月销售数据"且 Leader 判断需要问数能力
- **THEN** Leader SHALL 自主调用 `team_create` + `spawn_teammate` + `assign_task`，Teammate 完成后 Leader 汇总结果返回用户

### Requirement: 资源清理
系统 SHALL 在两个时机清理 Teammate 资源：(1) 每轮用户请求结束时焚毁本轮新建的 Teammate（与 `teammate-runtime-memory` 能力配合）；(2) 进程退出时清理仍残留的活跃团队与 Teammate，避免 asyncio Task 与文件残留。

#### Scenario: 每轮请求结束焚毁本轮 Teammate
- **WHEN** Leader 完成一轮用户请求的回复
- **THEN** 系统 SHALL 调用 `team_manager.cleanup_spawned_in_turn()`，对本轮 `spawn_teammate` 创建的所有 Teammate 发起 shutdown 并等待 Runner 退出

#### Scenario: 进程退出清理
- **WHEN** REPL 主循环退出（用户输入 exit 或进程终止）
- **THEN** 系统 SHALL 向所有活跃 Teammate 发送 shutdown 并清理其 asyncio Task 与 Task List 文件

#### Scenario: 活跃团队可查
- **WHEN** Leader 调用 `team_list`
- **THEN** 系统 SHALL 返回当前所有活跃团队及其成员状态，便于排查资源泄漏

### Requirement: Leader 通过 Mailbox 接收任务完成通知
系统 SHALL 让 Leader 通过 Mailbox 阻塞式等待 Teammate 的任务完成通知，避免 Leader 在 LLM 推理循环中反复轮询 task_list_query 造成的 token 浪费与延迟。

Runner 完成任务（成功或失败）时 SHALL 自动向 Leader 信箱投递一条结构化通知消息；Leader SHALL 通过 `wait_for_message` 工具阻塞挂起（不消耗 LLM 推理）直至消息到达或超时；TaskList 退回为工作池与依赖关系存储，不再充当"通知 Leader"的渠道。

#### Scenario: Runner 任务成功后自动投递完成通知
- **WHEN** Teammate Runner 在 `_run_one_turn` 中处理完一条 task（claim → 执行 → 完成）
- **THEN** Runner SHALL 在标记 task 为 completed 后自动通过 Mailbox 发送一条 `kind="task_completed"` 的消息给 Leader，消息内容为最终 AI 文本，`meta` 字段包含 `task_id` 与 `teammate_name`

#### Scenario: Runner 任务失败后投递失败通知
- **WHEN** Teammate Runner 在 `_run_one_turn` 中抛出未捕获异常或超时
- **THEN** Runner SHALL 通过 Mailbox 发送一条 `kind="task_failed"` 的消息给 Leader，`meta` 字段携带 `task_id` / `teammate_name` / `reason`，避免 Leader 永远等不到回信

#### Scenario: Leader 阻塞等待消息
- **WHEN** Leader 调用 `wait_for_message(timeout=N)` 工具
- **THEN** 系统 SHALL 让 Leader 协程在 Leader 信箱上阻塞挂起（不消耗 LLM token）直至收到消息或超过 timeout

#### Scenario: 等待超时
- **WHEN** Leader 调用 `wait_for_message` 在 timeout 内未收到任何消息
- **THEN** 工具 SHALL 返回 `{"status": "timeout"}`，Leader 可选择继续等待、查询 task_list_query 或向用户报告

#### Scenario: Runner 内消息处理也自动回信
- **WHEN** Teammate Runner 在 `_run_one_turn` 中处理一条来自 Leader 的 `kind="message"` 消息
- **THEN** Runner SHALL 在完成后通过 Mailbox 将 AI 文本作为 `kind="message_reply"` 投递回原发送者（meta 包含原消息标识），保证消息往返闭环

#### Scenario: TaskList 仍保留工作池语义
- **WHEN** 多个 Teammate 同时空闲
- **THEN** TaskList 的 claim 机制 SHALL 仍然有效（先到先得），且 blocked_by 依赖关系 SHALL 仍然约束领取顺序；mailbox 通知机制不替代这两项职责

### Requirement: 外部服务连接失败时明确报错
代理 Teammate 调用外部服务（NL2SQL 等）的工具 SHALL 在连接失败、超时、HTTP 错误时立即返回结构化错误并打印日志，禁止默默等待至 Runner 超时才暴露失败。

#### Scenario: 连接超时与读取超时分层
- **WHEN** 代理工具发起 HTTP 请求时
- **THEN** 系统 SHALL 设短连接超时（如 10 秒）以快速失败，与 SSE 流的读取超时（可不限）分开配置

#### Scenario: 工具失败时打印明确日志
- **WHEN** 代理工具捕获 `ConnectError` / `TimeoutException` / `NetworkError` / 4xx / 5xx
- **THEN** 系统 SHALL 在终端打印一条带前缀的错误日志（如 `[NL2SQL] ✗ connect failed: ConnectionRefusedError → 服务可能未启动`）并返回 `{"status": "error", "reason": "..."}` 结构

### Requirement: NL2SQL 请求与 SSE 事件实时日志
NL2SQL 代理工具 SHALL 在请求发出、SSE 事件到达、最终结果或错误时实时打印日志，便于排查"连不上 / SQL 错误 / 超时"等各类问题。

#### Scenario: 请求发出日志
- **WHEN** `nl2sql_query` / `nl2sql_list_databases` / `nl2sql_list_tables` 发起请求
- **THEN** 系统 SHALL 打印一条 `[NL2SQL] 🡒 <METHOD> <url>` 日志，附带核心参数（如 question / db_id）

#### Scenario: SSE 事件到达日志
- **WHEN** `nl2sql_query` 在 SSE 流中收到 `stage` / `result` / `error` / `done` 等事件
- **THEN** 系统 SHALL 打印一条 `[NL2SQL] 🡐 <event_type>: <摘要>` 日志（result 仅打 SQL 与行数，不打完整数据）

#### Scenario: 最终响应或错误日志
- **WHEN** 工具调用结束（成功 / 失败）
- **THEN** 系统 SHALL 打印一条最终汇总日志（如 `[NL2SQL] ✓ done sql=... rows=N` 或 `[NL2SQL] ✗ error: ...`）

### Requirement: 日志分层与前缀
终端日志 SHALL 按来源（Leader / Teammate / NL2SQL / 编排工具 / Mailbox / TaskList）打前缀并支持彩色高亮，避免不同层的输出混杂难以分辨。

#### Scenario: 前缀清晰可分辨
- **WHEN** 多个层同时输出
- **THEN** 每行日志 SHALL 以来源前缀开头（如 `[Leader]` / `[Teammate <name>]` / `[NL2SQL]` / `[Orchestrator]` / `[Mailbox]`），便于人工与脚本过滤

#### Scenario: 关键事件统一字符标记
- **WHEN** 打印工具调用 / 返回 / 错误 / 完成等事件
- **THEN** 系统 SHALL 统一使用约定的视觉字符（如 `🛠` 调用 / `📥` 返回 / `✗` 错误 / `✓` 成功 / `🡒` 请求出 / `🡐` 响应入）

#### Scenario: 彩色输出与降级
- **WHEN** 终端支持 ANSI 彩色
- **THEN** 不同来源的前缀 SHALL 使用不同前景色（Leader=cyan / Teammate=各自分配的色 / NL2SQL=magenta / Orchestrator=yellow / Mailbox=blue）；终端不支持 ANSI 时 SHALL 自动降级为纯文本输出
