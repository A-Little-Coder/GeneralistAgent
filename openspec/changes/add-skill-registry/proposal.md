## Why

中控 Agent 需要在规划阶段拿到全部可用 Skill / Teammate 的摘要、依赖、入参以做选择，并在执行阶段把它们以工具或 sub-agent 的形式装配进 deepagents。手写注册既繁琐又容易和文档脱节，应该按"约定优于配置"——扫描 `skills/` 目录、解析 `SKILL.md` 元数据自动注册。开发期还要让"改一行 SKILL.md 不重启服务"成为可能，缩短迭代循环。

## What Changes

- 定义 SKILL 目录约定：`skills/_common/`、`skills/teammates/`、每个 SKILL 一个目录、必含 `SKILL.md`
- 固化 `SKILL.md` 模板：YAML frontmatter（name/description/type/runtime/depends_on/inputs/outputs/triggers/max_retries）+ Markdown 正文（何时使用、调用方式）
- 实现 `SkillScanner`：启动期 glob 扫描，解析 frontmatter 校验 schema，去重检查，依赖闭合检查
- 实现 `SkillRegistry`（进程内单例）：`name → SkillSpec` 字典 + 摘要表（供规划层召回）
- 实现 deepagents 适配层：把 SkillSpec 转为 deepagents 期望的 sub_agent / tool 入参（隔离框架版本变化）
- 实现热加载：基于 `watchdog`，开发期通过环境变量 `SKILL_HOT_RELOAD=true` 启用；线上默认关闭
- 实现热加载防抖：500ms debounce、临时文件后缀过滤、文件大小稳定检测
- 启动后输出 `skills_manifest.json`，供 LangSmith 关联追踪

## Capabilities

### New Capabilities

- `skill-registry`: SKILL 扫描、解析、注册、deepagents 适配、热加载

### Modified Capabilities

（无）

## Impact

- 影响代码：`chatbi/infra/skill_registry/`（scanner、spec、registry、deepagents_adapter、hot_reload）
- 影响依赖：新增 `watchdog`、`pyyaml`、`pydantic`
- 影响目录：固化 `skills/` 一级与二级约定
- 后续依赖：`add-orchestrator-planner`、`add-teammate-protocol` 都消费本 change 产出的 Registry
