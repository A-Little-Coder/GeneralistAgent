# ChatBI Agent

供应链 BG ChatBI Web Chat 主入口的统一中控 Agent，基于 LangChain `deepagents` 框架。

## 项目简介

ChatBI Agent 把原先散落在多处的 Agent 能力（知识问答、NL2SQL、预测、归因、报表生成等）统一收敛到一个 Web Chat 入口。整体采用 4 层架构：

- **会话层**（`chatbi/conversation/`）：SSE 流、反问中断、限流。
- **中控 Agent 层**（`chatbi/orchestrator/`）：意图识别、检索、规划、路由。
- **能力层**（`chatbi/capabilities/`）：Teammate Agent 与通用工具。
- **基础设施层**（`chatbi/infra/`）：记忆、持久化、SKILL 注册、反问、通信。
- **可观测性横切**（`chatbi/observability/`）：LangSmith Tracer、上下文、LLM 工厂。

## 目录结构

```
GeneralistAgent/
├── chatbi/
│   ├── conversation/     # 会话层
│   ├── orchestrator/     # 中控 Agent 层
│   ├── capabilities/     # 能力层（teammates/, common_tools/）
│   ├── infra/            # 基础设施
│   ├── observability/    # 监控 / LangSmith
│   ├── cli/              # CLI 入口
│   └── server/           # FastAPI 入口
├── skills/               # SKILL 描述文件目录
├── evals/                # 测评数据集与脚本
├── learn/                # 教学 demo
├── tests/                # 单元 / 集成测试
├── scripts/              # 辅助脚本
├── .env.example
├── pyproject.toml
├── requirements.txt
└── openspec/             # OpenSpec 变更与规约
```

## 安装

> 必须使用清华镜像源（CLAUDE.md 第 5 条）。

```bash
# Linux / macOS / Git Bash
bash scripts/pip-install.sh

# PowerShell
powershell -ExecutionPolicy Bypass -File scripts/pip-install.ps1

# 或手动
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 配置

```bash
cp .env.example .env
# 填入 LANGSMITH_API_KEY 与 QWEN_API_KEY
```

## 最小运行示例

```bash
# 查看版本
chatbi version

# 跑通 LangSmith 接入
chatbi hello-trace
```

## 本地启动 FastAPI

```bash
uvicorn chatbi.server.app:app --reload --port 8000
# 健康检查
curl http://localhost:8000/healthz
```

## 日志规范

ChatBI 使用 `logging + rich.logging.RichHandler` 作为 root handler，默认中文输出，结构化字段通过 `extra=` 注入：

| 字段           | 必含 | 说明                           |
| -------------- | ---- | ------------------------------ |
| `event`        | 是   | 事件名（缺失自动填 `"log"`）   |
| `user_id`      | 否   | 用户 ID                        |
| `conv_id`      | 否   | 会话 ID                        |
| `plan_run_id`  | 否   | 规划执行 ID                    |
| `elapsed_ms`   | 否   | 耗时（毫秒）                   |
| `error`        | 否   | 错误对象 / 错误码              |

中文写法约定：日志消息以陈述句结尾，避免感叹号；优先使用动词短语（如「LangSmith 接入成功」「检索到 3 条候选」）。

## 测试

```bash
pytest tests/
```

## OpenSpec 工作流

变更先入 `openspec/changes/`，开发完成后再归档到 `openspec/specs/`。详见 `openspec/AGENTS.md` 与 `CLAUDE.md`。
