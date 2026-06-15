## ADDED Requirements

### Requirement: 数据集格式

系统 SHALL 把离线测评数据集按 `evals/datasets/<capability>/<version>.jsonl` 路径组织，每行一条 case，必含字段 `id`、`input`、`expected_output`（含 `answer_keywords`、`format`）、`expected_behavior`（字符串列表）、`capability`、`tags`、`source`、`created_at`；版本与 capability 名 kebab-case。

#### Scenario: 加载数据集

- **WHEN** `DatasetLoader.load("ask_data", "v1")` 调用
- **THEN** 返回 list[EvalCase]，长度 ≥ 5（每 capability 至少 5 条 seed）
- **AND** 每条字段完整通过 pydantic 校验

#### Scenario: 字段缺失

- **WHEN** 某行缺 `expected_behavior`
- **THEN** 抛 `EvalDatasetError` 指出文件名、行号、缺失字段

### Requirement: 4 类 Evaluator

系统 SHALL 实现 4 个 Evaluator（实现 LangSmith `RunEvaluator` / `EvaluatorCallable` 接口）：

- `task_completion`：trace 无异常且有 `final` 事件 → 1，否则 0
- `answer_quality`：用 LLM-as-judge（temperature=0）+ `with_structured_output` 输出 1–5 分
- `behavior_correctness`：解析 expected_behavior DSL（v1 支持 `call X N times` / `no extra calls` / `call sequence: A→B`），与 trace 中工具调用序列比对，输出 0–1 浮点
- `latency`：抽 trace metadata `total_ms`
- `cost`：抽 trace metadata `total_usd`

#### Scenario: behavior 完全匹配

- **WHEN** expected `["call ask_data exactly once","no extra teammate calls"]` 且 trace 仅 1 次 ask_data
- **THEN** behavior_correctness = 1.0

#### Scenario: behavior 部分匹配

- **WHEN** trace 多调用了一次未声明的 tool
- **THEN** behavior_correctness < 1.0（按规则数 / 满足规则数计算）

### Requirement: 综合满足率公式

系统 SHALL 在 Runner 中按 `satisfaction = 0.5*task_completion + 0.3*(answer_quality/5) + 0.2*behavior_correctness` 计算每条 case 的满足率，整体取均值；权重通过 Settings `eval_weights` 字段可配置。

#### Scenario: 默认权重

- **WHEN** 一条 case completion=1, quality=4, behavior=1
- **THEN** satisfaction = 0.5*1 + 0.3*(4/5) + 0.2*1 = 0.94

### Requirement: 离线 Runner CLI

系统 SHALL 提供 `chatbi eval run --dataset <capability>/<version> [--concurrency N] [--report PATH]`，行为：
- 顺序/并发执行所有 case；
- 每 case 调用中控（内部入口），收集 trace；
- 调用 4 类 Evaluator；
- 输出 Markdown 报告含汇总表 + 每分量均值 + 失败 TOP-10 + 与上版 diff（如同 dataset 上次运行存在）；
- LangSmith trace tag `eval_run=<run_id>`。

#### Scenario: 报告生成

- **WHEN** 执行 `chatbi eval run --dataset ask_data/v1`
- **THEN** `evals/reports/<run_id>.md` 文件被创建
- **AND** 文件含"综合满足率: xx%" 字符串
- **AND** stdout 输出报告路径与 LangSmith URL

### Requirement: 数据集冷启动

系统 SHALL 为每个已实现的 capability 提供 ≥ 5 条 seed case 在 `evals/datasets/<capability>/v1.jsonl`；本 change 至少为 `ask_data` capability 提供 seed。

#### Scenario: ask_data seed 存在

- **WHEN** 仓库 clone 后查看
- **THEN** `evals/datasets/ask_data/v1.jsonl` 行数 ≥ 5