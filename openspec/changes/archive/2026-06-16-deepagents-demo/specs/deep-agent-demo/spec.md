## ADDED Requirements

### Requirement: 多轮对话能力
Agent SHALL 支持连续多轮对话，在对话间保持上下文记忆。

#### Scenario: 多轮对话保持上下文
- **WHEN** 用户先问"我的名字是张三"，再问"我叫什么名字"
- **THEN** Agent 能正确回答"张三"

#### Scenario: 对话超出上下文窗口
- **WHEN** 对话经过多轮后接近模型上下文窗口限制
- **THEN** DeepAgents 的 SummarizationMiddleware SHALL 自动压缩历史消息

### Requirement: 工具调用能力
Agent SHALL 具备 DeepAgents 内置工具调用能力，包括任务规划、文件操作和命令执行。

#### Scenario: 任务规划
- **WHEN** 用户要求完成一个多步骤任务（如"研究某个话题并写一份总结"）
- **THEN** Agent SHALL 使用 `write_todos` 工具将任务拆解为子步骤并逐步执行

#### Scenario: 文件读写
- **WHEN** 用户要求"创建一个文件并写入内容"
- **THEN** Agent SHALL 使用 `write_file` 工具创建文件，并用 `read_file` 验证

#### Scenario: 命令执行
- **WHEN** 用户要求在 shell 中执行命令
- **THEN** Agent SHALL 使用 `execute` 工具执行命令并返回结果

### Requirement: 用户友好交互
Agent 的交互界面 SHALL 满足易用性要求。

#### Scenario: 中文回复
- **WHEN** 用户用中文提问
- **THEN** Agent SHALL 用中文回复

#### Scenario: 清晰展示思考过程
- **WHEN** Agent 在 debug 模式下执行多步推理
- **THEN** 控制台 SHALL 清晰展示 Think → Action → Observation 每一阶段

#### Scenario: 友好退出
- **WHEN** 用户输入 `exit`、`quit` 或 `q`
- **THEN** 程序 SHALL 优雅退出并打印结束语

### Requirement: 配置管理
系统 SHALL 通过 `.env` 文件管理所有敏感配置。

#### Scenario: 加载配置
- **WHEN** 程序启动时存在 `.env` 文件
- **THEN** SHALL 自动加载 `QWEN_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL` 等配置

#### Scenario: 配置缺失提示
- **WHEN** `.env` 文件不存在或 `QWEN_API_KEY` 为空
- **THEN** 程序 SHALL 打印清晰的错误提示并退出

#### Scenario: .env.example 模板
- **WHEN** 新开发者克隆项目
- **THEN** SHALL 存在 `.env.example` 文件作为配置参考