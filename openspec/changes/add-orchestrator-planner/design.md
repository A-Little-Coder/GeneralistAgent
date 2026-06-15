## Context

中控 Agent 的核心是"规划 → 路由 → 执行"这个 LangGraph 图。用户进 → 识别哪些能力可用（从 SkillRegistry 摘要表）→ 用 few-shot 案例辅助 LLM 规划出 DAG → 三态路由决定走哪条路径 → 执行并汇总 → 返回用户。这是整系统最复杂、最智能的环节。

本 change 定位为"规划大脑"，不涉及具体 Teammate 执行逻辑（在 `add-teammate-protocol`）、不涉及 SSE 交互（在 `add-streaming-conversation`），只负责规划阶段与抽象执行阶段。

## Goals / Non-Goals

**Goals:**
- LangGraph 主图：`intent → retrieve → plan → route → (execute_plan | self_solve | decline) → summarize`
- 融合召回：语义 embedding 相似度（0.6） + BM25（0.4），可配置
- 案例库管理：冷启动 seed.jsonl + 线上案例"待审核"回流 + 人工确认注入
- 规划器：用用户问 + 召回案例 + SkillSummary + 公共工具说明 生成结构化规划（JSON，含 DAG）
- 三态路由：multi-agent / self-solve / decline（缺能力）
- 规划失败兜底：schema 校验失败 / 成环 / 未注册能力 → 降级为 decline 或 self-solve
- 规划过程全部上 LangSmith trace；召回命中案例与得分一并上报
- 提供 evaluate 子命令：单条输入，输出规划全过程 JSON，便于调试

**Non-Goals:**
- 不实现反问（在 `add-teammate-protocol`）
- 不实现 SSE / 流式（在 `add-streaming-conversation`）
- 不实现记忆/状态持久化（调用 `add-memory-persistence` 的接口而已）
- 不实现具体 Teammate 业务

## Decisions

### 决策 1：LangGraph 主图

```
         ┌────────────────────┐
         │    用户问 + 上下文   │
         └────────┬───────────┘
                  ▼
   ┌──────────────────────────────┐
   │ intent ── 意图分类（粗粒度）     │
   │   (知识问答 / 查数据 / 预测/... ) │
   └────────┬──────────────────────┘
            ▼
   ┌──────────────────────────────┐
   │ retrieve ── 案例召回           │
   │  语义相似 + BM25 → top-K      │
   └────────┬──────────────────────┘
            ▼
   ┌──────────────────────────────┐
   │ plan ── LLM 规划               │
   │  → JSON {steps, deps, mode,  │
   │     capabilities, expected}  │
   └────────┬──────────────────────┘
            ▼
   ┌──────────────────────────────┐
   │ validate ── 规划校验            │
   │  JSON schema / 成环 / 能力存在   │
   └────────┬──────────────────────┘
            │ 失败 → 降级路由
            ▼
   ┌──────────────────────────────┐
   │ route ── 三态路由              │
   └────────┬──────┬──────┬───────┘
            │      │      │
     multi-agent │ self-solve │ decline
            │      │      │
            ▼      ▼      ▼
         sub─graph │ simple_tools │ return
         (Teammate)│ (mcp/skill)  │"缺失xxx"
            │      │
            └──────┘
               │
               ▼
   ┌──────────────────────────────┐
   │ summarize ── 汇总回答          │
   │  信息合并 + 来源标注           │
   └────────┬──────────────────────┘
            ▼
        最终用户回答
```

### 决策 2：案例库

- 存储路径：`evals/cases/planning/`
  - `seed.jsonl`（冷启动，手工编写 50–100 条）
  - `pending_review.jsonl`（在线回流，人工确认后才移入正式集）
  - `validated.jsonl`（已确认可用案例，规划 ler 自动从这读）

- 案例格式（JSONL 每行）：
```json
{
  "id": "case-001",
  "query": "上月华南区库存周转率是多少",
  "intent": "data_query",
  "tags": ["问数", "库存", "周转率"],
  "plan": {
    "mode": "multi-agent",
    "steps": [{"step": 1, "agent": "ask_data", "input": {"question": "华南区上月库存周转率"}}],
    "deps": []
  },
  "expected_behavior": ["call ask_data exactly once", "no extra tools"]
}
```

### 决策 3：融合召回

```
embedding_model = get_embeddings("default")  # langchain_openai
query_embedding = embed(query)

BM25 = rank_bm25.BM25Okapi(tokenized_corpus)  # 案例的 query 字段

def hybrid_scores(query, cases, alpha=0.6):
    semantic_scores = cosine_sim(query_embedding, case_embeddings)
    bm25_scores = BM25.get_scores(tokenize(query))

    for i in range(len(cases)):
        cases[i].score = alpha * semantic_scores[i] + (1-alpha) * bm25_scores[i]
    return sorted(cases, key=lambda c: c.score, reverse=True)[:top_k]
```

- `alpha` 默认 0.6，可在 Settings 配置
- 案例 embedding 在注册 / 热加载时预计算，启动时一次写入 `evals/cases/planning/embeddings.npy`（或 SQLite）
- `top_k` 默认 3，可配置

### 决策 4：规划器（LLM 调用）

```python
class Planner:
    async def plan(self, query, context, recalled_cases):
        prompt = self._build_prompt(query, context, recalled_cases, summary_table)
        schema = self._plan_output_schema()  # JSON Schema
        result = await llm.with_structured_output(schema).ainvoke(prompt)
        return StructuredPlan.model_validate(result)
```

- 用 LangChain `with_structured_output` 保证输出直接是结构化对象
- prompt 结构：系统指令（规划规则） + 召回案例（few-shot） + 用户问 + 可用能力摘要 + 回答格式

### 决策 5：三态路由

```python
class RouteDecision(BaseModel):
    mode: Literal["multi-agent", "self-solve", "decline"]
    decline_reason: str = ""       # mode=decline 时必填：缺失什么能力
    plan: StructuredPlan | None = None  # mode=multi-agent 时
    tools_to_call: list[str] = []  # mode=self-solve 时
```

将规划的输出传给 route 节点，route 节点判断：

| 规划判定 | 路由结果 | 后续 |
|---|---|---|
| 使用了 type=teammate 的 SKILL | multi-agent | 拉起对应 Teammate subagent |
| 仅使用 type=common 的 SKILL | self-solve | 在当前进程调 LangChain Tool |
| 无可用 SKILL 匹配 | decline | 返回"缺失xxx能力"，不执行 |

decline 中的"缺失 xxx"从 2 个来源：
① 显式已知缺失：`skills/teammates/` 无对应目录
② LLM 判断：规划试图使用某种能力但无 SkillSummary 匹配

### 决策 6：规划失败兜底

| 失败类型 | 兜底 |
|---|---|
| LLM 输出不合 structured_output schema | 重试 1 次；仍失败 → self-solve 模式（仅用简单工具回答） |
| 依赖成环（A→B→A） | 去环：丢弃成环 step，剩余 steps 仍可用 |
| 调用了不存在的 Skill name | 从规划中移除该 step，标记 warn 给用户 |
| 全部 step 无法执行 | 降级为 decline |

所有兜底事件在 LangSmith 标注 `mitigation=xxx`。

### 决策 7：执行 sub-graph（multi-agent）

- 多 Agent 模式：每个 step 中的 teammate 走 `TeammateFactory.spawn(name, ctx).call(payload, ctx)`
- 顺序按 deps 拓扑排序；无依赖的步骤并行
- 执行后把结果写入黑板（`BlackboardStore.set(rid, step.name, result)`）
- 汇总节点从黑板读所有步骤结果 → LLM 合并 → 回答

### 决策 8：LangSmith 埋点

- 整个规划过程在一个顶层 trace（run_name=`planning`）下
- 子 span：`intent`、`retrieve`（含 `recalled_case_ids` / `scores`）、`plan`（含 full plan JSON）、`route`、`execute:{step_name}`、`summarize`
- 每个 span 带 `model_name`、`tokens`、`elapsed_ms`

## Risks / Trade-offs

- [Risk] 召回+规划两阶段 LLM 调用增加了延迟 → Mitigation：embedding 模型用轻量模型；规划用 `with_structured_output` 单次调用返回结构化结果
- [Risk] 案例 embedding 冷启动时空集 → Mitigation：`seed.jsonl` 必须 ≥ 50 条；embedding 预计算不依赖 LLM，很快
- [Risk] BM25 在中文场景分词效果影响召回效果 → Mitigation：使用 `jieba` 分词的 tokenizer（Design 中未显式写，技术选型加入 Spec task）；支持切换 tokenizer 配置
- [Trade-off] 规划校验阶段仅在规划后做校验，不做"规划前的能力发现"（即不先查一下所有可调用 Skill 再规划，而是规划输出后才校验能力是否存在）；简化设计，但可能浪费一次 LLM 调用。

## Migration Plan

- 新建项目，无迁移
- 案例库 50 条 seed 与 `test_planning.py` 一起交付

## Open Questions

- 案例 embedding 预计算 / 本地存储的位置：暂定 `evals/cases/planning/embeddings.json`
- 规划器 prompt 模板是否需要在启动时从文件读取以支持调优 → 是，用 `prompts/planning/system.md` 文件