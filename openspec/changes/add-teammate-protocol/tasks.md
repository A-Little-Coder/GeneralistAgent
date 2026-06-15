## 1. 反问事件与 Hub

- [ ] 1.1 实现 `chatbi/infra/ask_back/events.py`：`AskBackEvent` 基类、`ChoiceAskBack`、`FillAskBack`，含 `discriminator='type'`
- [ ] 1.2 单元测试：构造、字段校验、序列化往返、type=choice 缺 options 报错
- [ ] 1.3 实现 `chatbi/infra/ask_back/hub.py`：`AskBackHub`（含 `asyncio.Queue` + `dict[event_id→Future]`）
- [ ] 1.4 实现 `raise_and_wait` / `resume` / `fail` / `current` / `pending_count`
- [ ] 1.5 实现 30 分钟超时（`asyncio.wait_for` 包 future）与队列上限（8）
- [ ] 1.6 单元测试：串行 pop 顺序、超时、队列满、并发 raise 与 resume

## 2. LangGraph 节点

- [ ] 2.1 实现 `chatbi/infra/ask_back/handler.py::AskBackInterruptHandler`，作为 LangGraph 节点
- [ ] 2.2 编写中断/续跑示意图（README 配图）
- [ ] 2.3 单元测试：mock LangGraph state，验证有/无 current 情况下的行为

## 3. raise_question 工具

- [ ] 3.1 实现 `chatbi/infra/ask_back/tools.py::make_raise_question_tool(hub)`，基于 `langchain_core.tools.StructuredTool`
- [ ] 3.2 入参 schema 用 pydantic 模型定义；工具内部按 type 构造 `ChoiceAskBack` / `FillAskBack`
- [ ] 3.3 单元测试：异步调用、参数校验、与 hub 集成

## 4. Teammate 基类与工厂

- [ ] 4.1 实现 `chatbi/capabilities/teammates/base.py::TeammateBase`、`TeammateContext`、`TeammateResult`
- [ ] 4.2 实现 `chatbi/capabilities/teammates/factory.py::TeammateFactory.spawn(name, ctx)`：根据 SkillRegistry 中 spec 加载对应 client.py
- [ ] 4.3 用 `importlib` 加载 `skills/teammates/<name>/client.py`，要求其中含 `Client` 类继承 `TeammateBase`
- [ ] 4.4 单元测试：spawn 行为、缺 client.py 报错

## 5. 统一重试

- [ ] 5.1 实现 `chatbi/capabilities/teammates/retry.py::with_retries(fn, spec)`：基于 `tenacity`，仅捕获 NetworkError/Timeout/5xx
- [ ] 5.2 在 `TeammateFactory.spawn` 返回的实例 `call` 外层包重试装饰器
- [ ] 5.3 LangSmith span 注入 `retry_attempt`
- [ ] 5.4 单元测试：4xx 不重试、5xx 重试到上限、metadata 正确

## 6. 示例 Teammate ask_data

- [ ] 6.1 编写 `skills/teammates/ask_data/SKILL.md`：name=ask_data, type=teammate, runtime=http, endpoint=${ASK_DATA_URL}, max_retries=2, triggers=[查询..., ...销量是多少]
- [ ] 6.2 编写 `skills/teammates/ask_data/client.py`：`Client(TeammateBase)` 用 httpx 调用 `${ASK_DATA_URL}/query`
- [ ] 6.3 编写 `skills/teammates/ask_data/prompts/system.md`
- [ ] 6.4 编写 `chatbi/capabilities/teammates/ask_data/__init__.py`（如需 Python 侧补充逻辑可放此）
- [ ] 6.5 集成测试 `tests/teammates/test_ask_data.py`：用 `httpx.MockTransport` 模拟服务，覆盖成功、4xx、5xx 重试、slot_fill 反问 4 种场景

## 7. deepagents 适配层注入

- [ ] 7.1 修改 `chatbi/infra/skill_registry/deepagents_adapter.py`：teammate subagent `tools` 列表中追加 `make_raise_question_tool(hub)`
- [ ] 7.2 hub 由调用方（中控）传入；适配层签名变 `to_deepagents_kwargs(registry, hub)`
- [ ] 7.3 单元测试：mock hub，断言 raise_question 工具进入 subagent.tools

## 8. 验收

- [ ] 8.1 全部新增 / 修改单元测试通过
- [ ] 8.2 `tests/teammates/test_ask_data.py` 4 个场景全过
- [ ] 8.3 在 LangSmith 后台能看到 ask_data 调用 trace 与 retry_attempt 标签
- [ ] 8.4 README 增加章节：《Teammate 接入指南》《反问组件使用》
