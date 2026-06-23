## MODIFIED Requirements

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
