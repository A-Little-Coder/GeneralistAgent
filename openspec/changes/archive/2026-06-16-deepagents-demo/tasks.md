## 1. 创建 .env.example

- [x] 1.1 在项目根目录创建 `.env.example`，包含 Qwen API 配置、LangSmith 和 BGE 可选配置项

## 2. 实现 src/agent_demo.py

- [x] 2.1 编写主程序文件，从 `.env` 加载配置、初始化 Qwen 模型
- [x] 2.2 用 `create_deep_agent` 创建 Agent，配置中文 system prompt 和 MemorySaver checkpoint
- [x] 2.3 实现 CLI 交互循环，支持多轮对话、调试输出、友好退出

## 3. 验证与清理

- [x] 3.1 运行 Agent 并测试基础对话能力（中文回复、上下文记忆）
- [x] 3.2 测试工具调用能力（write_todos、文件操作等）
- [x] 3.3 确认 `.env.example` 与实际 `.env` 字段一致