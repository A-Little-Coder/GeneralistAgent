## Why

上线前要求综合满足率 ≥ 87%，上线后要持续把失败样本回流到离线测评集，形成闭环。Agent 的离线评测不能只看"问题→答案"，还要校验中间过程（工具调用是否正确、是否存在无意义调用）。本 change 提供一套基于 LangSmith Evaluator + 本地数据集的离线/在线一体化测评流水线，并提供失败回流通道。

## What Changes

- 定义离线测评数据集格式：JSONL，每行 `{id, input, expected_output, expected_behavior, capability, tags}`
- 定义存储路径：`evals/datasets/<capability>/<version>.jsonl`（本地固定路径）
- 实现 Evaluator 集合（接入 LangSmith Evaluator 接口）：
  - `task_completion`：任务完成率（end-to-end 跑通且无异常）
  - `answer_quality`：LLM-as-judge 打分（0–5）
  - `behavior_correctness`：工具调用序列与 `expected_behavior` 比对
  - `latency` / `cost`：从 LangSmith trace 抽取
- 定义综合满足率公式（v1）：`0.5 × task_completion + 0.3 × answer_quality_normalized + 0.2 × behavior_correctness`，公式可配置
- 实现离线 Runner：`chatbi eval run --dataset xxx --version vN`，输出汇总报告 + 与上一版本的对比
- 实现在线失败回流：从 LangSmith 拉取失败 / 用户负反馈 trace，脱敏（SKU、客户、库存数字打码）后写入 `evals/datasets/<capability>/pending_review.jsonl`
- 实现回流审核：`chatbi eval triage` CLI，逐条人工标注 expected_output 与 expected_behavior 后并入正式数据集
- 提供 ≥ 5 条 seed case / capability 作为冷启动样例

## Capabilities

### New Capabilities

- `evaluation-offline`: 离线测评数据集、Evaluator、Runner、综合满足率
- `evaluation-online-feedback`: 在线 trace 拉取、脱敏、回流、人工审核

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/observability/evaluation/`、CLI 子命令
- 影响依赖：新增 `langsmith`（已有）、`pandas`、`tabulate`
- 影响数据：`evals/datasets/`、`evals/reports/`
- 依赖前置：`add-chatbi-foundation`（LangSmith 接入）、`add-orchestrator-planner`（被测对象）
