## ADDED Requirements

### Requirement: LangGraph 主图

系统 SHALL 基于 LangGraph 实现中控主图，节点 `intent`、`retrieve`、`plan`、`validate`、`route`、`execute`、`summarize`；边逻辑符合设计决策 1 的图拓扑；run_name 统一为 `planning`。

#### Scenario: 端到端 multi-agent

- **WHEN** 用户输入"上月华南区库存周转率是多少"
- **THEN** 过程最终回到 `summarize` 节点
- **AND** 完整 trace 含上述全部 7 个节点

#### Scenario: decline 提前结束

- **WHEN** 规划器输出无匹配能力（`mode: decline`）
- **THEN** 用户收到"能力不足，缺失xxx"回答
- **AND** `execute` 节点不被执行

### Requirement: 规划器结构化输出

系统 SHALL 使用 LangChain `with_structured_output` 让 LLM 输出 `StructuredPlan`（pydantic 模型），含字段 `mode`、`steps`（list of `Step` 含 `id`、`capability`、`inputs`、`expected_output`）、`deps`（list of `[from_step_id, to_step_id]`）。

#### Scenario: 输出合法

- **WHEN** 规划器返回 plan
- **THEN** `StructuredPlan.model_validate(plan)` 不抛错
- **AND** 所有 step 的 `capability` 可在 SkillRegistry 中找到

### Requirement: 规划失败兜底

系统 SHALL 在规划校验失败（schema / 成环 / 不存在的 capability）时执行兜底策略：schema 失败重试 1 次 → self-solve 降级；成环去环；不存在的能力从规划中移除；所有 step 不可用时 decline；兜底事件必须写入 LangSmith span `mitigation` 字段。

#### Scenario: 成环去环

- **WHEN** 规划 `deps` 含 `[A→B, B→C, C→A]`
- **THEN** 去环后保留 A→B、B→C，丢弃 C→A
- **AND** 最终 plan 中不包含 C→A