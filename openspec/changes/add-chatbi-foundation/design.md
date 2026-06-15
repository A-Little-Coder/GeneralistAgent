## Context

ChatBI Agent 是基于 LangChain `deepagents` 的供应链领域 Agent 项目。目前项目目录除了 `.claude/`、`.idea/`、`openspec/` 外几乎为空，需要从零搭建 Python 包结构、依赖管理、配置加载、日志、最小入口、LangSmith 接入。所有后续 6 个 change 都依赖本 change 的产出，因此目录与依赖一旦定下来必须保持稳定。

所有用户对话、注释、日志输出默认使用中文（CLAUDE.md 第 1 条），代码标识符仍为英文。pip 安装一律使用清华镜像源（CLAUDE.md 第 5 条）。Agent 生成的代码统一为 Python，沙箱预留，当前直接在本地 terminal 执行。

## Goals / Non-Goals

**Goals:**
- 一次性确定项目目录、Python 包结构、依赖列表、配置加载方式、日志规范
- 接通 LangSmith（环境变量 + Tracer + 项目名约定 + 一次 hello-trace 验证）
- 强制 LLM 调用入口统一为 LangChain 官方 `langchain_*` 包
- 提供最小可运行入口：CLI（用于本地调试）+ FastAPI 占位（用于会话层接入）
- 把 deepagents 跑通一个最小示例，验证依赖兼容与版本

**Non-Goals:**
- 不实现具体业务能力（规划、Skill 注册、Teammate 等都在后续 change）
- 不实现完整 SSE（在 `add-streaming-conversation`）
- 不实现持久化（在 `add-memory-persistence`）
- 不实现沙箱（仅预留接口，使用本地 terminal 直跑 Python）

## Decisions

### 决策 1：依赖管理选 `pyproject.toml` + `requirements.txt` 双轨

- 选择：用 `pyproject.toml` 定义工程（PEP 621），同时输出 `requirements.txt` 给 pip 用户与 CI
- 理由：`deepagents` 与 LangChain 生态都是 pyproject 优先；`requirements.txt` 兼容旧脚本与清华镜像 `pip install -r`
- 候选：仅 requirements.txt（简单但不能声明 build-backend）；poetry（多一层学习成本）
- 取舍：双轨增加少量同步成本，但符合社区主流

### 决策 2：目录结构

```
GeneralistAgent/
├── chatbi/
│   ├── __init__.py
│   ├── conversation/        # L1（占位，本 change 仅留空目录 + __init__.py）
│   ├── orchestrator/        # L2（占位）
│   ├── capabilities/        # L3（占位 + teammates/、common_tools/ 子目录）
│   ├── infra/               # L4
│   │   ├── memory/、persistence/、skill_registry/、ask_back/、communication/  # 占位
│   │   ├── config/          # 本 change 实现：env/.env 加载
│   │   └── logging/         # 本 change 实现：结构化日志
│   ├── observability/       # 横切
│   │   ├── langsmith_setup.py   # 本 change 实现
│   │   └── metrics.py            # 占位
│   ├── cli/                 # 本 change 实现：典型子命令骨架
│   │   └── main.py
│   └── server/              # 本 change 实现：FastAPI 占位
│       └── app.py
├── skills/
│   └── README.md            # 仅说明目录用途，结构由 add-skill-registry 固化
├── evals/
│   └── README.md
├── learn/                   # CLAUDE.md #7 教学 demo 目录
├── tests/
│   └── test_foundation.py   # 本 change 自带的最小测试
├── .env.example
├── pyproject.toml
├── requirements.txt
├── README.md
└── CLAUDE.md（已存在）
```

- 理由：与之前讨论一致，按 4 层 + 监控横切；占位目录此 change 只放 `__init__.py`，不写代码

### 决策 3：依赖列表（最小集）

```
langchain>=0.2
langchain-core>=0.2
langchain-openai>=0.1
deepagents>=0.0.5         # 跟随 LangChain 官方
langsmith>=0.1.99
langgraph>=0.2
pydantic>=2.5
python-dotenv>=1.0
pyyaml>=6.0
fastapi>=0.111
uvicorn>=0.30
typer>=0.12               # CLI
rich>=13                  # 日志/表格
pytest>=8                 # 测试
pytest-asyncio>=0.23
```

后续 change 会按需追加（watchdog、redis、aiosqlite、rank-bm25、httpx、tenacity、pandas、sse-starlette 等）；本 change 不提前引入避免冗余。

### 决策 4：LLM 调用入口必须 LangChain

- 规则：仓库内任何处调用 LLM 都必须经过 `langchain_*` 包（`ChatOpenAI` 等），禁止直接调用 `openai` / `anthropic` 原生 SDK
- 理由：LangSmith 自动通过 LangChain Callback 链路埋点，绕过会丢 trace
- 落地：`chatbi/observability/llm_factory.py` 提供 `get_chat_model(name=...)`，全项目通过它取模型
- 检查：测试用 grep / lint 阻止 `import openai` 直接调用

### 决策 5：LangSmith 接入

- 环境变量：`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT=chatbi-{env}`、`LANGCHAIN_TRACING_V2=true`、`LANGCHAIN_ENDPOINT=https://api.smith.langchain.com`
- 启动检查：`langsmith_setup.init()` 在 `chatbi/cli/main.py` 与 `chatbi/server/app.py` 启动时调用，缺失 KEY 仅 warn 不阻塞
- 项目名约定：`chatbi-dev` / `chatbi-staging` / `chatbi-prod`
- Hello-trace：`chatbi hello-trace` CLI 子命令，用 `ChatOpenAI` 跑一个最小问答，确认 LangSmith 后台能看到 trace
- run_name 与 metadata 默认注入：`user_id`、`conv_id`、`plan_run_id`（后续 change 填值）

### 决策 6：日志规范

- 库：`structlog` 是更优选项，但为减依赖先用标准 `logging` + `rich.logging.RichHandler`，结构化字段通过 `extra=` 注入
- 中文输出：默认 INFO 中文消息；DEBUG 可英文
- 字段：`event`、`user_id`、`conv_id`、`plan_run_id`、`elapsed_ms`、`error`

### 决策 7：配置加载

- `python-dotenv` 加载 `.env` → `os.environ`
- `chatbi/infra/config/settings.py` 用 `pydantic-settings`（包含在 pydantic v2）暴露 `Settings` 单例
- 优先级：环境变量 > `.env` > 默认值

### 决策 8：清华镜像 pip 源约定

- 提供 `scripts/pip-install.sh`（bash）与 `scripts/pip-install.ps1`（PowerShell），自动加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- README 中明确写「请使用 `scripts/pip-install` 或自带 `-i` 参数」

## Risks / Trade-offs

- [Risk] deepagents 还在快速演进，0.x 版本 API 可能 breaking → Mitigation：在 `pyproject.toml` 锁次版本号 `~=0.0.5`，并把 deepagents 调用集中到 `chatbi/orchestrator/graph.py` 一个文件，方便升级
- [Risk] LangSmith 不可达（内网 / 海外限速）会让本地启动卡住 → Mitigation：`init()` 用 5s 超时，失败仅 warn，不阻塞启动
- [Risk] `langchain` 与 `langgraph` 版本兼容矩阵复杂 → Mitigation：先以 deepagents 的 `extras` 为准，必要时显式钉版本
- [Trade-off] 一次性引入 fastapi / uvicorn 即使 L1 还没实现，但避免之后再改依赖；占位 `app.py` 仅 1 个 `/healthz`

## Migration Plan

- 本 change 是新建项目，无迁移
- 与已存在的 `.claude/`、`.idea/`、`openspec/` 共存，不动现有 `.gitignore` 之外的内容
- 验收顺序：`pip install` → `pytest` → `chatbi hello-trace` 三步全过即收

## Open Questions

- LangSmith 项目命名是否需按团队规范（如 `bg-supplychain-chatbi-{env}`）？等接入实际 LangSmith 工作区后调整
- 是否要在 foundation 里就引入 `langfuse` 作为 LangSmith 备份？暂不引入，避免双轨埋点
