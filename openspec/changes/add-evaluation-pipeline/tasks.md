## 1. 数据集格式与加载

- [ ] 1.1 在 `chatbi/observability/evaluation/dataset.py` 定义 `EvalCase` pydantic 模型
- [ ] 1.2 实现 `DatasetLoader.load(capability, version) -> list[EvalCase]`
- [ ] 1.3 单元测试：合法、缺字段、空文件
- [ ] 1.4 在 `evals/datasets/ask_data/v1.jsonl` 编写 ≥ 5 条 seed case

## 2. Evaluator 集合

- [ ] 2.1 实现 `chatbi/observability/evaluation/evaluators/task_completion.py`
- [ ] 2.2 实现 `evaluators/answer_quality.py`：LLM-as-judge prompt + with_structured_output
- [ ] 2.3 实现 `evaluators/behavior_correctness.py`：DSL 解析（`call X N times` / `no extra calls` / `call sequence: A→B`）
- [ ] 2.4 实现 `evaluators/latency_cost.py`：从 trace metadata 抽取
- [ ] 2.5 单元测试：每个 evaluator 用 mock trace 覆盖典型情况

## 3. 综合满足率

- [ ] 3.1 实现 `chatbi/observability/evaluation/satisfaction.py::compute(case_results, weights)`
- [ ] 3.2 weights 从 Settings 读取（默认 0.5/0.3/0.2）
- [ ] 3.3 单元测试

## 4. 离线 Runner

- [ ] 4.1 实现 `chatbi/observability/evaluation/runner.py::OfflineRunner.run(dataset, concurrency)`
- [ ] 4.2 内部入口：调用中控 graph 的同步包装（不走 SSE）
- [ ] 4.3 trace tag `eval_run=<run_id>`
- [ ] 4.4 报告生成（Markdown）：汇总 / 失败 TOP-10 / 上版 diff
- [ ] 4.5 CLI `chatbi eval run`
- [ ] 4.6 集成测试：mock 中控 + mock LangSmith，跑通 ask_data 5 条

## 5. 在线失败回流

- [ ] 5.1 实现 `chatbi/observability/evaluation/feedback/puller.py::pull_runs(since, negative_only)` 调 LangSmith API
- [ ] 5.2 实现 `feedback/desensitize.py`：数字、SKU、邮箱、手机、公司名
- [ ] 5.3 单元测试：典型敏感串覆盖
- [ ] 5.4 写入 `pending_review.jsonl`
- [ ] 5.5 CLI `chatbi eval pull`

## 6. 人工审核 Triage

- [ ] 6.1 实现 `feedback/triage.py::TriageSession`：逐条交互 + y/n/s + 输入 expected_keywords / expected_behavior
- [ ] 6.2 写入 validated.jsonl，从 pending 移除
- [ ] 6.3 CLI `chatbi eval triage`
- [ ] 6.4 集成测试：模拟 stdin

## 7. 闭环 e2e

- [ ] 7.1 `tests/eval/test_feedback_loop.py`：mock LangSmith → 拉取 → 脱敏 → triage → eval run 完整链路
- [ ] 7.2 验证端到端通

## 8. 文档

- [ ] 8.1 README《测评流水线》章节：离线运行、回流、人工审核
- [ ] 8.2 编写 `docs/eval/expected_behavior_dsl.md`
- [ ] 8.3 在 CLAUDE.md 备忘：满足率公式可改、上线门槛 87%

## 9. 验收

- [ ] 9.1 全部测试通过
- [ ] 9.2 `chatbi eval run --dataset ask_data/v1` 成功输出报告
- [ ] 9.3 LangSmith 中可见 `eval_run` tag 与各 Evaluator 分数
- [ ] 9.4 `chatbi eval pull` + `chatbi eval triage` 跑通示例