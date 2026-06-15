## Why

终端 BG 供应链库存管理平台 ChatBI Web Chat 主入口面临 Agent 能力散点开发、调用不规范、缺乏统一入口的痛点。需要一个基于 LangChain DeepAgent 的统一中控 Agent 项目作为承载底座，把后续的中控、能力层、基础设施和监控全部安放进来，并从一开始就把 LangSmith 可观测性接通。本 change 负责把"地基"打好，让其余 6 个 change 都可以直接往里面填东西，避免每个 change 自己重复造目录与配置。

## What Changes

- 建立 4 层架构（会话层 / 中控 Agent 层 / 能力层 / 基础设施层）+ 监控横切的项目骨架
- 选定 LangChain `deepagents` 作为中控 Agent 框架，固化版本与最小可运行示例
- 统一 LLM 调用入口：所有 LLM 调用必须通过 LangChain 官方接口（`langchain_*`），保证 LangSmith 自动埋点
- 接入 LangSmith：环境变量、Tracer、项目命名规范、最小 hello-trace 示例
- 提供项目级配置加载（环境变量 + `.env` + 默认值）和日志规范（中文输出，结构化字段）
- 提供 Python 包结构 `chatbi/`、`skills/`、`evals/`、`learn/`、`tests/` 与最小可跑入口（CLI / FastAPI 占位）
- 统一 Agent 生成代码语言为 Python（沙箱预留，当前在本地 terminal 运行）
- 统一中文规范：注释、日志、文件输出、用户对话默认中文（代码标识符英文）
- 提供 pip 安装脚本，强制使用清华镜像源

## Capabilities

### New Capabilities

- `foundation`: 项目骨架、依赖、配置加载、目录约定、Python 入口
- `observability`: LangSmith 接入、Tracer 初始化、项目命名、追踪上下文工具

### Modified Capabilities

（无，本 change 为新建）

## Impact

- 影响代码：新建 `chatbi/`、`skills/`、`evals/`、`learn/`、`tests/` 全部目录
- 影响依赖：新增 `langchain`、`langchain-core`、`langchain-openai`、`deepagents`、`langsmith`、`pydantic`、`pyyaml`、`python-dotenv`、`fastapi`、`uvicorn`、`pytest`
- 影响配置：新增 `.env.example`、`pyproject.toml` 或 `requirements.txt`
- 后续依赖：所有其他 6 个 change 都依赖本 change 完成的目录与 LangSmith 初始化
