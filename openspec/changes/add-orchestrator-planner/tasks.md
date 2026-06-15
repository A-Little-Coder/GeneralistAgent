## 1. 案例库与 seed 数据

- [ ] 1.1 创建 `evals/cases/planning/` 目录 + 3 个 JSONL 文件（空或 seed）
- [ ] 1.2 手工编写 ≥ 50 条 seed 案例（覆盖知识问答、问数、预测、归因、报告生成、混合任务、能力不足 七类）
- [ ] 1.3 实现 `chatbi/orchestrator/case_store.py::CaseStore`：读取 validated.jsonl、pending_review.jsonl；append_to_pending()、approve_to_validated()
- [ ] 1.4 单元测试：读写、去重、大数据量

## 2. 融合召回

- [ ] 2.1 安装 `rank-bm25`、`jieba`、`numpy`（清华源）
- [ ] 2.2 实现 `chatbi/orchestrator/retriever.py::HybridRetriever`
- [ ] 2.3 embedding 预计算与缓存 (`evals/cases/planning/embeddings.json`)
- [ ] 2.4 BM25 tokenizer（`jieba.cut`），空案例库全量 > full 兜底
- [ ] 2.5 alpha 可配置（Settings），top_K 可配置
- [ ] 2.6 单元测试：空库返回空、得分排序、alpha=1/alpha=0 极端行为

## 3. 规划器

- [ ] 3.1 定义 `StructuredPlan` 与 `Step` pydantic 模型（含 id/capability/inputs/expected_output）
- [ ] 3.2 编写规划 prompt 模板 `prompts/planning/system.md`
- [ ] 3.3 实现 `chatbi/orchestrator/planner.py::Planner.plan(query, recalled_cases, summary_table)`
- [ ] 3.4 使用 `with_structured_output` 输出结构化 plan
- [ ] 3.5 单元测试：mock LLM 返回合法 / 不合法输出，验证格式化

## 4. 规划校验

- [ ] 4.1 实现 `chatbi/orchestrator/validator.py::validate(plan, registry) -> ValidationResult`
- [ ] 4.2 JSON schema 校验、成环检测（拓扑排序）、能力存在校验
- [ ] 4.3 兜底策略：schema 失败重试 1 次；成环去环；缺能力移除 step
- [ ] 4.4 单元测试：成环、缺能力、合法规划

## 5. 三态路由

- [ ] 5.1 定义 `RouteDecision` pydantic 模型
- [ ] 5.2 实现 `chatbi/orchestrator/router.py::RouteTriage`，根据 validate 后的 plan 与 registry 做路由
- [ ] 5.3 decline 原因生成：从 registry 查缺失能力
- [ ] 5.4 单元测试：三种模式的输入→输出

## 6. 执行 sub-graph

- [ ] 6.1 multi-agent 模式：按拓扑排序执行 TeammateFactory.spawn(name).call(payload)，结果写黑板
- [ ] 6.2 self-solve 模式：调用公共 LangChain Tool
- [ ] 6.3 decline 模式：直接生成回答字符串
- [ ] 6.4 汇总节点：从黑板读结果 → LLM 合并
- [ ] 6.5 单元测试：mock Teammate 与 Tool，验证 3 条路径

## 7. LangGraph 主图

- [ ] 7.1 实现 `chatbi/orchestrator/graph.py::build_planning_graph() -> CompiledGraph`
- [ ] 7.2 所有 7 个节点按 design 决策 1 拓扑组装
- [ ] 7.3 注入 LangSmith Tracer，每个节点一个 span，所有 span 带 `plan_run_id`
- [ ] 7.4 单元测试：mock 全部节点，验证图结构可编译

## 8. 评估 CLI / 调试

- [ ] 8.1 `chatbi eval plan --query "上月华南库存周转率"` → 输出规划 JSON 全部节点
- [ ] 8.2 与 `add-chatbi-foundation` 的 hello-trace 同风格
- [ ] 8.3 README 章节：《中控 Agent 规划架构》

## 9. 集成测试

- [ ] 9.1 `tests/orchestrator/test_full_planning.py`：mock 全部外部依赖，执行完整图
- [ ] 9.2 覆盖 3 种路由 + 案例召回命中/未命中
- [ ] 9.3 覆盖全部兜底策略
- [ ] 9.4 LangSmith trace 可看到全链路 7 个节点

## 10. 验收

- [ ] 10.1 全部测试通过
- [ ] 10.2 `chatbi eval plan ...` 可在本地运行并输出完整 JSON
- [ ] 10.3 LangSmith 看到规划 trace