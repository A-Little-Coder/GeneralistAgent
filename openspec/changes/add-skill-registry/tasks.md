## 1. SkillSpec 模型与解析

- [ ] 1.1 在 `chatbi/infra/skill_registry/spec.py` 定义 `SkillType`、`Runtime` 枚举与 `SkillInput` / `SkillOutput` 子模型
- [ ] 1.2 定义 `SkillSpec`（pydantic v2），含 frontmatter 全字段 + `body_md`（正文）
- [ ] 1.3 实现 `parse_skill_md(path: Path) -> SkillSpec`：分离 YAML frontmatter 与正文，做 env 变量插值（`${VAR}`），通过 pydantic 校验
- [ ] 1.4 单元测试：合法 / 缺字段 / 非 kebab-case / env 插值 / 缺 endpoint when runtime=http

## 2. Scanner

- [ ] 2.1 在 `chatbi/infra/skill_registry/scanner.py` 实现 `SkillScanner.scan(root="skills/")`
- [ ] 2.2 路径前缀校验、name 唯一性校验、depends_on 闭合校验
- [ ] 2.3 错误聚合：收集所有问题再一次性抛 `SkillScanError`（中文消息含每条原因）
- [ ] 2.4 单元测试：用临时目录构造各类失败用例

## 3. Registry

- [ ] 3.1 在 `chatbi/infra/skill_registry/registry.py` 实现 `SkillRegistry` 单例：`bootstrap(specs)`、`get(name)`、`upsert(spec)`、`remove(name)`、`summary_table()`、`names()`
- [ ] 3.2 启动后写出 `skills/_manifest.json`
- [ ] 3.3 `SkillSummary` 数据类：`name / description / type / inputs_brief / triggers`
- [ ] 3.4 单元测试：bootstrap、upsert、remove、并发读

## 4. deepagents 适配层

- [ ] 4.1 在 `chatbi/infra/skill_registry/deepagents_adapter.py` 实现 `to_deepagents_kwargs(registry) -> dict`
- [ ] 4.2 `teammate` 转 subagent：组装 `name / description / prompt`（读取 body_md）/ `tools`（注入 raise_question 占位 + client 占位）
- [ ] 4.3 `common` 转 LangChain `BaseTool`（用 `StructuredTool.from_function`，函数体此 change 仅做 `NotImplementedError` 占位，由各 SKILL 自身实现）
- [ ] 4.4 加 `DEEPAGENTS_VERSION_TESTED` 常量与启动期版本比对 WARNING
- [ ] 4.5 单元测试：mock Registry 含 teammate / common 各 1 个，断言 kwargs 结构

## 5. 热加载

- [ ] 5.1 在 `chatbi/infra/skill_registry/hot_reload.py` 实现 `SkillFileHandler`（继承 `FileSystemEventHandler`），含 debounce、后缀过滤、文件大小稳定检测
- [ ] 5.2 实现 `start_watcher(registry, root)`，仅当 `SKILL_HOT_RELOAD=true` 启动
- [ ] 5.3 测试：不启用时不启动；启用后修改 SKILL.md 触发 upsert
- [ ] 5.4 README/文档说明 watchdog 仅开发期

## 6. 启动集成

- [ ] 6.1 在 `chatbi/server/app.py` `startup` 事件中调用 `SkillScanner.scan` + `SkillRegistry.bootstrap` + `start_watcher`
- [ ] 6.2 在 `chatbi/cli/main.py` 增加子命令 `chatbi skill list` 与 `chatbi skill validate`，便于本地巡检
- [ ] 6.3 启动失败时让 FastAPI 抛出，不进入 serving

## 7. 集成测试

- [ ] 7.1 `tests/skill_registry/test_end_to_end.py`：在 tmp 目录建一个 `_common/foo/SKILL.md` 与 `teammates/ask_data/SKILL.md`，跑全流程
- [ ] 7.2 测试：启动失败用例（重名、依赖缺失）
- [ ] 7.3 测试：`to_deepagents_kwargs` 输出可被 mock 的 `create_deep_agent` 接受
- [ ] 7.4 测试：plan_run 期间热加载不影响当前快照（用一个 fake plan_run lock）
