## ADDED Requirements

### Requirement: 三态路由

系统 SHALL 在 `route` 节点根据规划器的输出 `StructuredPlan` 执行三态路由：
- `multi-agent`：按拓扑排序启动 Teammate；
- `self-solve`：在当前进程内用公共 LangChain Tool 处理；
- `decline`：不执行任何能力，直接返回"能力不足，缺失 xxx"。

#### Scenario: multi-agent 按拓扑执行

- **WHEN** plan 含 step A（无依赖）、B（depends on A）、C（无依赖）
- **THEN** A 与 C 同时执行（并发）
- **AND** B 在 A 完成后执行

### Requirement: decline 原因

系统 SHALL 在 `decline` 模式中根据 SkillRegistry 检查缺失的能力名称：如果 LLM 试图使用某能力但 Registry 无对应 name，输出"能力不足，缺失{name}"；如果 LLM 表达的意图在 Registry 中无任何匹配，输出"能力不足，当前不支持的 query 类型"。

#### Scenario: 已知缺失能力

- **WHEN** 规划用到 `forecasting` 但 `skills/teammates/forecasting/` 不存在
- **THEN** 回答：暂时缺失预测能力

#### Scenario: 完全未知

- **WHEN** 用户问"帮我在腾讯买股票"
- **THEN** 回答：不支持的查询类型