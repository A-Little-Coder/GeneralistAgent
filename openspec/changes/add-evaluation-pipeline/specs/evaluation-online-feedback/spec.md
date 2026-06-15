## ADDED Requirements

### Requirement: 失败样本拉取

系统 SHALL 提供 `chatbi eval pull --since <date> [--negative-only]`，调用 LangSmith API 拉取指定时间窗内的 run，过滤条件：
- `negative_only=True`：仅 tag 含 `negative_feedback` 或 `error` 或用户反馈差的 run；
- 默认：上述条件 + 任意 LLM 输出长度异常（< 5 字符或 > 4000 字符）的 run。

#### Scenario: 时间过滤

- **WHEN** 执行 `chatbi eval pull --since 2026-06-14`
- **THEN** 拉取的 run 全部时间戳 ≥ 2026-06-14
- **AND** 写入 pending_review.jsonl

### Requirement: 脱敏

系统 SHALL 对拉取的 run（user query 与 final answer）执行脱敏：
- 6 位以上数字串 → `<NUM>`；
- SKU / 物料号正则 `[A-Z]{2,}-\d{4,}` → `<SKU>`；
- 客户/公司名白名单匹配 → `<COMPANY>`；
- 邮箱、手机号、身份证 → 各自占位符。

脱敏前后均通过单元测试覆盖典型敏感串。

#### Scenario: 数字脱敏

- **WHEN** 原文含 "库存 1234567 件"
- **THEN** 脱敏后含 `<NUM>` 替换原数字

#### Scenario: SKU 脱敏

- **WHEN** 原文含 "SKU SH-12345"
- **THEN** 脱敏后含 `<SKU>` 替换

### Requirement: 待审核与人工审核

系统 SHALL 写入回流数据到 `evals/datasets/<capability>/pending_review.jsonl`（不直接进 validated）；提供 `chatbi eval triage --capability <c>` 交互 CLI：
- 逐条显示 input / 实际回答（脱敏后）/ trace 摘要；
- 询问 [y]纳入 / [n]丢弃 / [s]跳过；
- 选 y 后询问 expected_keywords（逗号分隔）、expected_behavior（多行结束 `EOF`）；
- 写入 validated.jsonl 并从 pending 移除该条。

#### Scenario: triage 通过

- **WHEN** 用户选择 y 并输入关键词与行为
- **THEN** 该条进入 validated.jsonl，pending 中被移除

#### Scenario: triage 丢弃

- **WHEN** 用户选择 n
- **THEN** 该条从 pending 移除，不进 validated

### Requirement: 闭环验收

系统 SHALL 形成"线上失败 → 拉取 → 脱敏 → 待审 → 人审 → 进入数据集 → 重新评测"完整闭环；提供 `tests/eval/test_feedback_loop.py` 端到端用例 mock LangSmith API，覆盖全链路。

#### Scenario: 全链路通

- **WHEN** 端到端测试运行
- **THEN** 模拟的失败 run 最终成为 validated 数据集的一条
- **AND** 重新 `eval run` 时该条被纳入评测