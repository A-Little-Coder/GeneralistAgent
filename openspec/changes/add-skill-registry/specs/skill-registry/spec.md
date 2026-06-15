## ADDED Requirements

### Requirement: SKILL 目录约定

系统 SHALL 要求所有 SKILL 必须位于 `skills/_common/<name>/` 或 `skills/teammates/<name>/` 路径下，每个 SKILL 目录至少包含一个 `SKILL.md` 文件，文件名固定大小写。

#### Scenario: 合法路径被识别

- **WHEN** `skills/teammates/ask_data/SKILL.md` 存在并合法
- **THEN** 启动后 `SkillRegistry.get("ask_data")` 返回对应 `SkillSpec`

#### Scenario: 非法路径被拒绝

- **WHEN** `skills/foo/SKILL.md` 存在（不在 `_common/` 或 `teammates/` 下）
- **THEN** 启动直接报错并退出，错误信息中文指出非法路径

### Requirement: SKILL.md frontmatter schema

系统 SHALL 用 `pydantic` 模型 `SkillSpec` 校验 `SKILL.md` 的 YAML frontmatter，必填字段 `name`（kebab-case）、`description`、`type`（枚举：`teammate`/`common`/`sub_agent`）、`runtime`（枚举：`mcp`/`http`/`local`），可选字段 `endpoint`、`depends_on`、`inputs`、`outputs`、`triggers`、`max_retries`、`timeout_s`。

#### Scenario: 缺失必填字段

- **WHEN** `SKILL.md` 缺少 `description`
- **THEN** 启动失败，错误指出文件路径与缺失字段

#### Scenario: 名称非 kebab-case

- **WHEN** `name: AskData`
- **THEN** 校验失败

#### Scenario: 环境变量插值

- **WHEN** `endpoint: ${ASK_DATA_URL}` 且环境变量 `ASK_DATA_URL=https://x.com`
- **THEN** `SkillSpec.endpoint` 解析后为 `https://x.com`

### Requirement: 启动期扫描注册

系统 SHALL 在应用启动时调用 `SkillScanner.scan("skills/")` 扫描全部 `SKILL.md`，校验 name 唯一性与 `depends_on` 闭合性，将结果灌入 `SkillRegistry` 单例并产出 `skills/_manifest.json`。

#### Scenario: 名称冲突

- **WHEN** 两个目录的 `SKILL.md` 都声明 `name: ask_data`
- **THEN** 启动失败，错误列出全部冲突路径

#### Scenario: 依赖未声明

- **WHEN** `attribution` 的 `depends_on: [ask_data_v999]`，但 `ask_data_v999` 不存在
- **THEN** 启动失败

#### Scenario: 正常启动产出 manifest

- **WHEN** 全部 SKILL 合法
- **THEN** `skills/_manifest.json` 写出含全部 SkillSummary 的 JSON

### Requirement: 摘要表用于规划层

系统 SHALL 暴露 `SkillRegistry.summary_table() -> list[SkillSummary]`，每条 `SkillSummary` 含 `name`、`description`、`type`、`inputs_brief`、`triggers`，供规划层做 few-shot 召回。

#### Scenario: 摘要表内容稳定

- **WHEN** 多次调用 `summary_table()` 而无热加载事件
- **THEN** 返回同一对象引用或等价内容

### Requirement: deepagents 适配层

系统 SHALL 提供 `to_deepagents_kwargs(registry) -> dict` 函数，把当前 Registry 转换成 `deepagents.create_deep_agent` 期望的 `subagents` / `tools` 入参，并自动给每个 `teammate` 类型注入 `raise_question` 工具。

#### Scenario: teammate 转 subagent

- **WHEN** Registry 含一个 `type=teammate, name=ask_data` 的 spec
- **THEN** 返回 dict 的 `subagents` 列表中存在 `{"name": "ask_data", ...}` 一项
- **AND** 该项的 `tools` 包含名为 `raise_question` 的工具

#### Scenario: common 转 tool

- **WHEN** Registry 含一个 `type=common, name=plan_recall`
- **THEN** 返回 dict 的 `tools` 列表中存在对应 LangChain `BaseTool` 实例

### Requirement: 热加载（开发期）

系统 SHALL 当环境变量 `SKILL_HOT_RELOAD=true` 时启用 watchdog 监听 `skills/` 递归变更，触发 `SkillRegistry.upsert / remove` 进行原子内存替换，热加载流程必须做 500ms debounce、临时文件后缀过滤、文件大小稳定检测。

#### Scenario: 默认关闭

- **WHEN** `SKILL_HOT_RELOAD` 未设置
- **THEN** `start_watcher()` 返回 `None`，不启动 Observer

#### Scenario: 启用后修改触发重载

- **WHEN** 环境变量已设为 `true`，启动后修改 `skills/teammates/ask_data/SKILL.md` 的 `description`
- **THEN** 500ms 内 `SkillRegistry.get("ask_data").description` 反映新值

#### Scenario: 临时文件忽略

- **WHEN** 编辑器创建 `.SKILL.md.swp`
- **THEN** Registry 不发生变化

### Requirement: 规划运行期 schema 一致性

系统 SHALL 保证 deepagents kwargs 在一次 `plan_run` 内不受热加载影响：每次 `plan_run` 启动时调用 `to_deepagents_kwargs()` 获取一份快照，运行期间不再重算。

#### Scenario: 运行中改 SKILL 不影响当前 run

- **WHEN** plan_run 进行中，外部修改了某 SKILL
- **THEN** 当前 run 仍使用启动时快照
- **AND** 下一次 plan_run 使用新快照

### Requirement: 启动失败处理

系统 SHALL 在 Skill 注册阶段任何错误（schema、唯一性、依赖闭合、IO）均使应用启动失败并打印中文错误，不允许"半成功"启动。

#### Scenario: 半数 SKILL 失败

- **WHEN** 10 个 SKILL 中 1 个 frontmatter 解析失败
- **THEN** 应用启动失败
- **AND** stderr 列出失败的文件与原因
