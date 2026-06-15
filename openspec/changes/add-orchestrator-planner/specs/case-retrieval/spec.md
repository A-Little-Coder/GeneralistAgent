## ADDED Requirements

### Requirement: 案例库结构

系统 SHALL 在 `evals/cases/planning/` 下维护 3 个 JSONL 文件：`seed.jsonl`（冷启动 ≥50 条）、`validated.jsonl`（已确认可用）、`pending_review.jsonl`（在线回流待审）；每条案例包含 `id`、`query`、`intent`、`tags`、`plan`（含 mode、steps、deps）、`expected_behavior`、`embedding`（可选，预计算后写回）。

#### Scenario: seed 文件存在

- **WHEN** 首次启动
- **THEN** `seed.jsonl` 中至少有 50 条案例
- **AND** `validated.jsonl` 初始化时与 seed.jsonl 同内容（或空，由首次构建填充）

### Requirement: 融合召回

系统 SHALL 实现 `HybridRetriever`，支持 `retrieve(query, top_k=3) -> list[ScoredCase]`，使用语义 embedding 相似度（权重 `alpha`，默认 0.6）+ BM25 得分（权重 `1-alpha`）融合排序；`alpha` 通过 Settings 可配；embedding 使用 LangChain Embeddings 接口。

#### Scenario: 空案例库

- **WHEN** validated.jsonl 为空
- **THEN** `retrieve()` 返回空列表，规划器仅在无 few-shot 情况下工作

#### Scenario: 得分排序

- **WHEN** 案例 A（语义高、BM25 低）、B（语义中、BM25 中）、C（语义低、BM25 高）
- **THEN** 结果按融合得分降序排列

### Requirement: 案例 embedding 预计算

系统 SHALL 在启动时 / 案例库更新时预计算全部案例的 embedding（调用 Embeddings 模型），结果写回 `evals/cases/planning/embeddings.json`；开发期可跳过预计算。

#### Scenario: 启动加载

- **WHEN** 启动时 `embeddings.json` 存在
- **THEN** `HybridRetriever` 直接加载，不重新计算

### Requirement: 在线回流接口

系统 SHALL 提供 `CaseRecorder.record(case, origin_trace_id, is_approved=False)`，当 is_approved=False 时写入 `pending_review.jsonl`，当 is_approved=True 时直接写入 `validated.jsonl`。

#### Scenario: 待审核

- **WHEN** `record(case)` 未传 `is_approved`
- **THEN** case 写入 `pending_review.jsonl`

#### Scenario: 直接通过

- **WHEN** `record(case, is_approved=True)`
- **THEN** case 写入 `validated.jsonl` 并触发 embedding 增量更新