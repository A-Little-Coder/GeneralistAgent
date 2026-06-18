## Context

当前项目是一个名为 GeneralistAgent 的空壳项目，`src/` 目录为空。已验证以下技术组件可用：

- **LLM**: 阿里 Qwen（`qwen3.6-plus`），通过 OpenAI 兼容接口调用
- **DeepAgents**: `deepagents==0.6.10` 已安装，`create_deep_agent` 已通过端到端测试
- **LangSmith**: 链路追踪已配置

本项目旨在基于 DeepAgents 框架搭建一个最小可用的智能体 demo，作为后续开发的基础骨架。

## Goals / Non-Goals

**Goals:**
- 在 `src/agent_demo.py` 中创建一个基于 `create_deep_agent` 的 CLI 交互式 Agent
- Agent 使用 Qwen 模型（通过 `langchain.chat_models.init_chat_model` 传入 OpenAI 兼容 endpoint）
- 支持 DeepAgents 内置工具：write_todos、read/write/edit_file、ls/glob/grep、execute、task
- 多轮对话能力（MemorySaver checkpoint）
- 提供 `.env.example` 模板

**Non-Goals:**
- 不涉及自定义工具或额外 middleware
- 不涉及前端/API 服务
- 不涉及生产部署
- 不涉及测试用例（demo 阶段）

## Decisions

| 决策 | 选型 | 理由 |
|------|------|------|
| 模型初始化 | `init_chat_model("openai:qwen3.6-plus", base_url=..., api_key=...)` | Qwen 兼容 OpenAI 协议，`init_chat_model` 是 DeepAgents 推荐方式 |
| Agent 框架 | `create_deep_agent()` 默认配置 | 开箱即用，自带全部内置工具 |
| 对话持久化 | `MemorySaver()` | DeepAgents 内置支持，实现多轮对话记忆 |
| 系统提示词 | 中文 prompt | 项目使用中文，Agent 需用中文回复 |
| 交互方式 | CLI input() 循环 | 最简单直观的交互方式 |
| 调试模式 | `debug=True` | 便于观察 Agent 的思考过程 |
| 依赖管理 | 列出依赖说明，不引入新工具 | 保持最小依赖 |

## Risks / Trade-offs

- [低] Qwen 模型的工具调用能力可能不如 Claude/OpenAI — 但验证测试已通过
- [低] `deepagents==0.6.10` 仍在快速迭代 — demo 阶段无影响
- [低] 不使用 `response_format` 结构化输出 — demo 阶段保持简单