## MODIFIED Requirements

### Requirement: 多轮对话能力
Agent SHALL 支持连续多轮对话，通过 MemorySaver + thread_id 保持上下文记忆。

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
Agent 的交互界面 SHALL 满足易用性要求，采用异步流式输出实时呈现生成过程。

#### Scenario: 中文回复
- **WHEN** 用户用中文提问
- **THEN** Agent SHALL 用中文回复

#### Scenario: 流式实时输出
- **WHEN** 用户提交请求，LLM 开始生成回复
- **THEN** 控制台 SHALL 通过 `astream` 逐 token 实时打印生成内容，用户能看到文字逐步出现，而非等待全部生成后一次性输出

#### Scenario: 清晰展示思考过程
- **WHEN** Agent 在 debug 模式下执行多步推理
- **THEN** 控制台 SHALL 在节点边界清晰展示 Think → Action → Observation 每一阶段，区分 AI 输出段与工具返回段

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

## ADDED Requirements

### Requirement: 技能热更新
Agent SHALL 通过 SkillCenter 在运行中感知技能变更并自动加载最新技能。

#### Scenario: 运行时更新技能
- **WHEN** 用户在 Agent 运行中修改了某个 SKILL.md
- **THEN** 下一次用户输入后 Agent SHALL 自动加载更新后的技能内容

#### Scenario: 运行时新增技能
- **WHEN** 用户在 Agent 运行中添加了新的 skill 目录
- **THEN** 下一次用户输入后 Agent SHALL 能识别并使用新技能

#### Scenario: 请求级重实例化
- **WHEN** 每次用户输入新的请求
- **THEN** Agent SHALL 重新实例化（create_deep_agent），确保 system prompt 包含最新技能

### Requirement: 多模块架构
Agent 代码 SHALL 按职责拆分为多个模块。

#### Scenario: 职责分离
- **WHEN** 开发者查看代码结构
- **THEN** config / model / agent / skill_center / cli / main 各模块职责清晰可独立修改

#### Scenario: 模块可测试
- **WHEN** 开发者测试某一模块
- **THEN** SHALL 可以直接导入该模块，不依赖其他模块的全部功能

### Requirement: 计算器技能
Agent SHALL 内置计算器技能，通过 Python 执行精确算术运算。

#### Scenario: 基础四则运算
- **WHEN** 用户提出数学计算请求（如"123.45 * 67.89"）
- **THEN** Agent SHALL 使用 execute 工具调用 python 命令完成精确计算

#### Scenario: 复杂表达式
- **WHEN** 用户提出含括号和优先级的表达式
- **THEN** Agent SHALL 使用 python -c "print(...)" 执行并返回结果