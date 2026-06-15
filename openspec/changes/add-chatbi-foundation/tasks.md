## 1. 项目初始化与依赖

- [x] 1.1 在仓库根创建 `pyproject.toml`（PEP 621），声明项目名 `chatbi`、版本 `0.1.0`、依赖列表（design 决策 3）
- [x] 1.2 生成同步的 `requirements.txt`（与 `pyproject.toml` 字段一一对应）
- [x] 1.3 创建 `scripts/pip-install.sh` 与 `scripts/pip-install.ps1`，自动追加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`
- [x] 1.4 编写 CI / 本地校验脚本 `scripts/check_requirements_sync.py` 检测 `pyproject.toml` 与 `requirements.txt` 不同步
- [x] 1.5 创建 `.env.example`，列出 `LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`、`CHATBI_ENV`、`OPENAI_API_KEY`、`OPENAI_BASE_URL` 占位
- [x] 1.6 更新根目录 `README.md`：项目简介、目录结构、安装命令（清华源）、最小运行示例

## 2. Python 包骨架

- [x] 2.1 创建 `chatbi/__init__.py`（含 `__version__`）
- [x] 2.2 创建子包 `chatbi/conversation/`、`chatbi/orchestrator/`、`chatbi/capabilities/teammates/`、`chatbi/capabilities/common_tools/`、`chatbi/infra/{memory,persistence,skill_registry,ask_back,communication}/`、`chatbi/observability/`、`chatbi/cli/`、`chatbi/server/`，各自带 `__init__.py`
- [x] 2.3 创建顶层占位目录 `skills/`（含 `README.md`）、`evals/`（含 `README.md`）、`learn/`、`tests/`
- [x] 2.4 在 `tests/__init__.py` 与 `tests/conftest.py` 写好 pytest 基础配置（asyncio mode、tmp_path 共享 fixture）

## 3. 配置加载

- [x] 3.1 实现 `chatbi/infra/config/settings.py`：`Settings`（pydantic-settings）含 `langsmith_api_key`、`langsmith_project`、`chatbi_env`、`openai_api_key`、`openai_base_url`、`openai_model_default`、`log_level` 等字段
- [x] 3.2 在 `chatbi/__init__.py` 顶部调用 `python-dotenv` 的 `load_dotenv()` 加载根目录 `.env`
- [x] 3.3 暴露 `get_settings()` 单例函数，加 `@lru_cache`

## 4. 日志与中文输出

- [x] 4.1 实现 `chatbi/infra/logging/setup.py`：`configure_logging(level)` 用 `RichHandler` 输出，统一 `format` 与 `datefmt`
- [x] 4.2 提供 `get_logger(name)` 包装，注入默认 `extra` 字段（`event` 缺失即填名为 "log"）
- [x] 4.3 编写 README 章节《日志规范》：必含字段、中文写法约定

## 5. LLM 工厂与 LangSmith 接入

- [x] 5.1 实现 `chatbi/observability/llm_factory.py::get_chat_model(name="default")`，基于 `langchain_openai.ChatOpenAI`，支持从 Settings 读取 base_url / api_key / model_name
- [x] 5.2 实现 `chatbi/observability/langsmith_setup.py::init()`，按 design 决策 5 流程；缺凭证只 warn
- [x] 5.3 实现 `chatbi/observability/context.py::get_trace_context()`，基于 `contextvars` 维护 `user_id` / `conv_id` / `plan_run_id` / `retry_attempt`
- [x] 5.4 修改 `get_chat_model` 内部默认注入 `RunnableConfig(metadata=...)`（来自 `get_trace_context()`）

## 6. CLI 与 FastAPI 入口

- [x] 6.1 实现 `chatbi/cli/main.py`（typer）：子命令 `version`、`hello-trace`
- [x] 6.2 在 `pyproject.toml` 注册 `chatbi = "chatbi.cli.main:app"` 入口点
- [x] 6.3 实现 `chatbi/server/app.py`：FastAPI 实例 `app`、`GET /healthz`、`startup` 事件中调用 `langsmith_setup.init()` 与 `configure_logging()`
- [x] 6.4 README 增加《本地启动》章节：`uvicorn chatbi.server.app:app --reload`

## 7. 测试

- [x] 7.1 编写 `tests/test_foundation.py::test_packages_importable`：所有声明子包均可 import
- [x] 7.2 `test_settings_loading`：临时 `.env` + monkeypatch 环境变量，验证优先级
- [x] 7.3 `test_get_chat_model_returns_basechatmodel`：mock OPENAI_API_KEY，断言返回类型且 `callbacks` 非空
- [x] 7.4 `test_cli_version`：用 `typer.testing.CliRunner` 调用 `version`
- [x] 7.5 `test_healthz`：用 `httpx.AsyncClient` + ASGITransport 命中 `/healthz`
- [x] 7.6 `test_no_native_llm_sdk`：用 ast 扫描 `chatbi/` 全部 `.py`，禁止 `import openai` / `from openai`（白名单：`chatbi/observability/llm_factory.py` 不允许出现，langchain_openai 内部除外）
- [x] 7.7 `test_trace_context_defaults`：未进入上下文时 `get_trace_context()` 返回各字段为空串

## 8. 验收

- [x] 8.1 `bash scripts/pip-install.sh` 一次性安装成功
- [x] 8.2 `pytest tests/` 全部通过
- [x] 8.3 配置好 `LANGSMITH_API_KEY` 与 `QWEN_API_KEY` 后 `chatbi hello-trace` 正常输出回答
- [x] 8.4 在 LangSmith 后台对应项目下能看到 `hello-trace` 记录
- [ ] 8.5 在 CLAUDE.md 中追加一行：项目骨架与 LangSmith 接入完成（人工执行）
