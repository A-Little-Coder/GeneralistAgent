## Context

ChatBI Agent 上线前需达到综合满足率 ≥ 87%，上线后要持续把失败样本回流到离线测评集形成迭代闭环。Agent 评测难点：① 不能只看"问题→答案"，必须看中间过程（工具调用是否正确、是否存在无意义调用）；② 评测必须可重复运行，对比不同版本；③ 在线 trace 含敏感信息（SKU、客户、库存数字），回流前必须脱敏。

LangSmith 已经接入（在 `add-chatbi-foundation`），本 change 在其 Evaluator 接口上构建项目专属的离线/在线测评流水线。

## Goals / Non-Goals

**Goals:**
- 离线数据集格式（JSONL，含 `expected_output` + `expected_behavior`）+ 本地存储路径
- 4 类 Evaluator：`task_completion`、`answer_quality`（LLM-as-judge）、`behavior_correctness`、`latency`/`cost`
- 综合满足率 v1 公式：`0.5 × completion + 0.3 × quality_norm + 0.2 × behavior`
- 离线 Runner CLI：`chatbi eval run --dataset xxx`，输出报告 + 与上版对比
- 在线失败回流：从 LangSmith 拉取负反馈/失败 trace → 脱敏 → 写 `pending_review.jsonl`
- 人工审核 CLI：`chatbi eval triage` 逐条标注后并入正式数据集

**Non-Goals:**
- 不实现 A/B 流量切分（线上 A/B 由网关层做）
- 不实现自动批改答案的"完全正确"判定（用 LLM-as-judge 给分即可）
- 不实现可视化前端（先 Markdown / 表格输出）

## Decisions

### 决策 1：数据集格式

```
evals/datasets/<capability>/
├── v1.jsonl                  # 当前版本
├── pending_review.jsonl      # 在线回流待审
└── archived/v0.jsonl         # 历史版本
```

每条 case：
```json
{
  "id": "data-q-001",
  "input": {"query": "上月华南库存周转率"},
  "expected_output": {
    "answer_keywords": ["华南", "库存周转率"],
    "must_contain_data": true,
    "format": "text"
  },
  "expected_behavior": [
    "call ask_data exactly once",
    "no extra teammate calls"
  ],
  "tags": ["问数", "库存"],
  "capability": "ask_data",
  "source": "manual",
  "created_at": "2026-06-15"
}
```

`expected_behavior` 是字符串列表，由 `behavior_correctness` Evaluator 通过启发式规则匹配 trace 中的 tool_call 序列。

### 决策 2：Evaluator 集合

| Evaluator | 输入 | 输出 | 实现 |
|---|---|---|---|
| `task_completion` | trace + final answer | 0 或 1 | trace 无未捕获异常 + 有 final 事件 |
| `answer_quality` | answer + expected_keywords | 0–5 分 | LLM-as-judge prompt + structured_output |
| `behavior_correctness` | trace + expected_behavior | 0–1 浮点 | 启发式：解析 expected 的 DSL（如 "call X N times"），与 trace 对比 |
| `latency` | trace | 毫秒数 | 从 trace metadata 抽 |
| `cost` | trace | 美元数 | 从 trace metadata 抽 |

LLM-as-judge prompt：
```
你是评分员。给定用户问题、模型回答、预期关键词、预期格式，输出 1-5 分整数：
- 1: 完全错误
- 3: 部分正确
- 5: 完全正确
请输出 JSON：{"score": int, "reason": str}
```

### 决策 3：综合满足率公式 v1

```
quality_norm = answer_quality / 5    # 归一到 0–1
satisfaction = 0.5 * task_completion
             + 0.3 * quality_norm
             + 0.2 * behavior_correctness
```

- 整体满足率 = 全部 case 的 `satisfaction` 平均值
- 公式权重在 Settings 可改，便于后期调
- 报告中会同时输出每个分量的均值，便于诊断

### 决策 4：离线 Runner

```
chatbi eval run \
  --dataset ask_data/v1 \
  --concurrency 5 \
  --report evals/reports/run-20260615-123456.md
```

执行流程：
1. 读取 `evals/datasets/<capability>/<version>.jsonl`
2. 每条 case 调用中控（同 `/api/chat/stream` 等价的内部接口，但同步收集事件）
3. 提交到 LangSmith Evaluator
4. 聚合分数 → 输出 Markdown 报告（含每分量均值、失败 case 详情、与上版对比）

### 决策 5：在线失败回流

```
chatbi eval pull --since 2026-06-14 --negative-only
```

执行流程：
1. 用 LangSmith API 拉取符合条件的 run（按 tag `negative_feedback` / `error` / 用户标"差"）
2. 调脱敏函数 `desensitize(text)`：
   - 数字 → 替换为 `<NUM>`
   - SKU / 物料号（正则 `[A-Z]{2,}-\d{4,}`）→ `<SKU>`
   - 公司/客户名（白名单匹配）→ `<COMPANY>`
3. 写入 `pending_review.jsonl`（不直接进 validated）
4. 提示：`已回流 N 条到 pending_review，请用 chatbi eval triage 审核`

### 决策 6：人工审核

```
chatbi eval triage --capability ask_data
```

交互式 CLI：
- 读取 pending_review.jsonl
- 逐条展示 input / 实际回答 / trace 摘要
- 询问：是否纳入数据集？(y/n) → 期望关键词？→ 期望行为？
- 写入 `validated.jsonl` 并从 pending 移除

### 决策 7：报告与对比

报告 `evals/reports/<run_id>.md` 含：
- 摘要表：综合满足率、4 个 Evaluator 均值
- 与上一次同 dataset 运行的 diff（哪些 case 由通转败）
- TOP-10 失败 case 详情（含 trace 链接）

### 决策 8：与 LangSmith 集成

- 离线 Runner 调用中控时给 trace 加 tag `eval_run=<run_id>`
- LangSmith Evaluator 注册到项目，运行时自动在 trace 上挂分
- 报告里附带 LangSmith run URL

## Risks / Trade-offs

- [Risk] LLM-as-judge 偏置 → Mitigation：温度=0；使用 GPT-4 或同等级模型；公式权重低（30%）
- [Risk] expected_behavior DSL 表达能力有限 → Mitigation：v1 仅支持 3 种规则（`call X N times`、`no extra calls`、`call sequence: A→B`），后续按需扩
- [Risk] 脱敏不彻底 → Mitigation：脱敏前后人工 spot-check + 单元测试覆盖典型敏感串
- [Trade-off] 报告 Markdown 而非 HTML：易 git diff，但可视化弱，先够用

## Migration Plan

- 新建项目，无迁移
- 后续可把 `pending_review` 替换为 LangSmith Dataset，但当前需求"本地固定路径"明确

## Open Questions

- 是否需要每天自动跑回流？暂不做定时任务，由人手动 `eval pull`
- 历史报告如何归档？暂存 `evals/reports/`，每月人工归档