## ADDED Requirements

### Requirement: 项目目录结构

系统 SHALL 在仓库根目录建立以下 Python 包结构：`chatbi/`（含 `conversation/`、`orchestrator/`、`capabilities/`、`infra/`、`observability/`、`cli/`、`server/` 子包）、`skills/`、`evals/`、`learn/`、`tests/`，每个 Python 包必须包含 `__init__.py`。

#### Scenario: 新克隆仓库后目录完整

- **WHEN** 开发者执行 `git clone` 后查看根目录
- **THEN** 上述全部目录与 `__init__.py` 存在
- **AND** `chatbi/` 下每个子包均可 `python -c "import chatbi.<sub>"` 成功导入

### Requirement: 依赖与安装

系统 SHALL 通过 `pyproject.toml` 与同步生成的 `requirements.txt` 声明全部 Python 依赖，提供 `scripts/pip-install.sh` 与 `scripts/pip-install.ps1` 自动追加清华镜像源。

#### Scenario: 使用清华源安装依赖

- **WHEN** 开发者执行 `bash scripts/pip-install.sh`
- **THEN** 命令实际执行 `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
- **AND** 安装成功后 `python -c "import langchain, deepagents, langsmith, langgraph, fastapi"` 不报错

#### Scenario: pyproject 与 requirements 同步

- **WHEN** 开发者修改 `pyproject.toml` 中的依赖
- **THEN** `requirements.txt` 必须在同一次提交中同步更新
- **AND** CI 校验脚本能检测到不同步并拒绝合并

### Requirement: LLM 调用必须经过 LangChain

系统 MUST 强制所有 LLM 调用通过 `langchain_*` 系列包发起，由 `chatbi/observability/llm_factory.py` 暴露的 `get_chat_model(name=...)` 工厂函数获取模型实例，禁止仓库代码直接 `import openai` / `anthropic` 等原生 SDK 进行模型调用。

#### Scenario: 通过工厂获取模型

- **WHEN** 业务代码需要一个 LLM 客户端
- **THEN** 必须调用 `get_chat_model("default")` 取得 `BaseChatModel` 实例
- **AND** 该实例自动挂上 LangSmith Tracer

#### Scenario: 直接调用原生 SDK 被拒

- **WHEN** 仓库内出现 `import openai` 或同等绕过行为
- **THEN** `tests/test_foundation.py::test_no_native_llm_sdk` 必须失败

### Requirement: 配置加载

系统 SHALL 在启动时通过 `python-dotenv` 加载根目录 `.env` 至 `os.environ`，并由 `chatbi.infra.config.settings.Settings` 单例（基于 `pydantic-settings`）按"环境变量 > `.env` > 默认值"的优先级提供配置访问。

#### Scenario: 优先级生效

- **WHEN** `.env` 中 `LANGSMITH_PROJECT=chatbi-dev`，外部环境变量同时设置 `LANGSMITH_PROJECT=chatbi-staging`
- **THEN** `Settings().langsmith_project` 返回 `chatbi-staging`

### Requirement: 中文输出与日志规范

系统 SHALL 默认以中文输出 INFO 级别日志、用户对话、文件输出与注释，使用 `logging + rich.logging.RichHandler` 作为 root handler，强制日志中包含结构化字段 `event` 以及（可选）`user_id`、`conv_id`、`plan_run_id`、`elapsed_ms`。

#### Scenario: 启动日志为中文

- **WHEN** 执行 `chatbi hello-trace`
- **THEN** stdout 至少有一行包含中文（如「LangSmith 接入成功」）
- **AND** 日志行包含 `event=` 字段

### Requirement: CLI 与 FastAPI 入口

系统 SHALL 提供基于 `typer` 的 CLI 入口 `chatbi`（含子命令 `hello-trace`、`version`），以及基于 FastAPI 的服务入口 `chatbi.server.app:app`，至少暴露 `GET /healthz` 返回 `{"status":"ok"}`。

#### Scenario: CLI version

- **WHEN** 执行 `chatbi version`
- **THEN** 输出非空版本号字符串

#### Scenario: 健康检查

- **WHEN** 启动 `uvicorn chatbi.server.app:app` 并访问 `GET /healthz`
- **THEN** HTTP 200 返回 `{"status":"ok"}`

### Requirement: 测试基线

系统 SHALL 在 `tests/test_foundation.py` 提供以下测试用例并全部通过：包路径可导入、Settings 加载、`get_chat_model` 工厂可调用（mock LLM 即可）、CLI `version` 命令、`/healthz` 路由、禁止原生 SDK 检查。

#### Scenario: 全部测试通过

- **WHEN** 执行 `pytest tests/test_foundation.py`
- **THEN** 退出码为 0
- **AND** 报告中显示至少 6 个测试用例
