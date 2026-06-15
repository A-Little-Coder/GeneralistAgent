## Why

中控 Agent 收到用户问题后，需要先判定走哪条路径：① 涉及 Teammate 能力的多 Agent 模式、② 自身用公共 SubAgent/MCP/SKILL 处理的简单任务、③ 能力不足直接拒答。该判定与任务规划质量直接决定整个系统的满足率。本 change 把"规划 + 案例召回 + 三态路由"这一核心智能落地，并通过 few-shot + 语义相似性 + BM25 融合召回提升规划质量。

## What Changes

- 实现中控 Agent 的 LangGraph 主图：`理解 → 召回案例 → 规划 → 三态路由 → 执行 → 汇总回答`
- 实现案例库（冷启动手工撒种 50–100 条），存储于本地固定路径 `evals/cases/planning/*.jsonl`
- 实现融合召回：语义相似度（embedding）+ BM25，权重默认 0.6 / 0.4 可配置
- 实现规划器：基于用户问 + 召回案例 + 已注册 Teammate 摘要 + 公共工具说明，产出结构化规划（含 DAG 依赖、工作模式）
- 实现三态路由：multi-agent / self-solve / decline；decline 时给出"能力不足，缺失 xxx"
- 实现规划失败兜底：JSON schema 校验失败、依赖成环、调用未注册 Skill 三种情况的回退策略
- 把召回明细（哪些案例、命中分）+ 规划 JSON 全部上报 LangSmith，作为后续迭代依据
- 提供线上案例回流接口（仅记入待审核库，业务确认后才注入正式案例库）

## Capabilities

### New Capabilities

- `orchestrator-planning`: 中控 Agent 任务规划与依赖拓扑构建
- `case-retrieval`: 案例库管理与语义+BM25 融合召回
- `route-triage`: 三态路由（multi-agent / self-solve / decline）

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/orchestrator/`（planner、case_retriever、router、graph）
- 影响依赖：新增 `rank-bm25`、`langchain-openai`（embedding）、`numpy`
- 影响数据：新增 `evals/cases/planning/seed.jsonl`、`evals/cases/planning/pending_review.jsonl`
- 依赖前置：依赖 `add-chatbi-foundation`（项目骨架与 LangSmith）、`add-skill-registry`（拿到 Skill/Teammate 摘要表）
