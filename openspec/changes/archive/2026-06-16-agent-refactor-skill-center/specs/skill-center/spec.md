## ADDED Requirements

### Requirement: Skill 持久化存储
SkillCenter SHALL 使用 SQLite 作为技能持久化存储。

#### Scenario: 创建技能表
- **WHEN** SkillCenter 首次初始化
- **THEN** SHALL 自动创建 `skills` 表（name, description, version, content, triggers, updated_at）

#### Scenario: 添加技能
- **WHEN** 用户执行 `add` 操作（name, description, content）
- **THEN** SHALL 写入 SQLite 记录，并同步写入 `skills/{name}/SKILL.md`

#### Scenario: 更新技能
- **WHEN** 用户执行 `update` 操作
- **THEN** SHALL 更新 SQLite 记录，并覆盖 `skills/{name}/SKILL.md`

#### Scenario: 删除技能
- **WHEN** 用户执行 `delete` 操作
- **THEN** SHALL 删除 SQLite 记录，并删除 `skills/{name}/` 目录

#### Scenario: 列表查询
- **WHEN** 用户执行 `list` 操作
- **THEN** SHALL 从 SQLite 查询并展示所有技能的名称、版本和更新时间

### Requirement: 变更检测
SkillCenter SHALL 通过版本 hash 检测技能是否发生变更。

#### Scenario: 技能未变
- **WHEN** 两次请求间 skills/ 目录无变化
- **THEN** decorate_state() SHALL 保留 state 中的 skills_metadata，零磁盘 IO

#### Scenario: 技能新增
- **WHEN** 有新的 skill 目录被添加到 skills/
- **THEN** decorate_state() SHALL 清除 state 中的 skills_metadata，触发 SkillsMiddleware 重读

#### Scenario: 技能内容修改
- **WHEN** 已有 SKILL.md 内容被修改
- **THEN** decorate_state() SHALL 清除 state 中的 skills_metadata，触发 SkillsMiddleware 重读

#### Scenario: 技能删除
- **WHEN** 某个 skill 目录被删除
- **THEN** decorate_state() SHALL 清除 state 中的 skills_metadata，触发 SkillsMiddleware 重读

### Requirement: CLI 管理入口
SkillCenter SHALL 提供命令行管理接口。

#### Scenario: 管理命令格式
- **WHEN** 用户执行 `python -m src.skill_center add my-skill "描述" --content "..."` 
- **THEN** SkillCenter SHALL 解析参数并执行对应操作

#### Scenario: 参数缺失提示
- **WHEN** 用户执行管理命令但缺少必要参数
- **THEN** SHALL 打印清晰的用法提示

### Requirement: SKILL.md 标准格式
SKILL.md 文件 SHALL 遵循标准格式以便 SkillsMiddleware 正确解析。

#### Scenario: YAML frontmatter
- **WHEN** SkillsMiddleware 扫描 skill 目录
- **THEN** SHALL 通过 YAML frontmatter 正确提取 name 和 description 字段