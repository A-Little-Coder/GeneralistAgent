## Why

当前项目 `src/` 是空的，没有可运行的智能体。需要基于 LangChain 开源的 DeepAgents 框架（`deepagents` 包）快速搭建一个可运行的 Agent demo，验证 Qwen API 与 DeepAgents 的集成，并建立 `.env` 配置规范。

## What Changes

- 在 `src/` 下新增 `agent_demo.py`：一个基于 DeepAgents `create_deep_agent` 构建的 CLI 交互式智能体
- 新增 `.env.example`：环境变量配置模板，包含 Qwen API 配置及可选配置项
- Agent 具备 DeepAgents 内置能力：任务规划（write_todos）、文件读写、命令执行、子代理委派

## Capabilities

### New Capabilities
- `deep-agent-demo`: 基于 DeepAgents 框架构建的通用智能体 CLI demo，支持多轮对话、内置工具调用（规划、文件、shell）

### Modified Capabilities

<!-- 无现有规格需要修改 -->

## Impact

- `src/agent_demo.py` — 新增 demo 入口文件
- `.env.example` — 新增环境变量模板
- `requirements.txt` 或依赖说明 — 确认依赖项（deepagents, langchain-openai, python-dotenv）
- 无现有代码修改