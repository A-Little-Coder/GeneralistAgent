## Context

当前项目只有一个 `src/agent_demo.py`（~150 行），集成了 DeepAgents，并已验证 Qwen API + 工具调用可行。但代码耦合严重，缺乏技能管理体系。需要拆分为多模块架构，引入标准化的 Skill 管理和热更新能力。

现有资产：
- DeepAgents 0.6.10（已安装）
- Qwen API (openai 兼容接口)
- LangChain / LangGraph 生态

## Goals / Non-Goals

**Goals:**
- 单文件拆分为 6 个职责清晰的模块（config / model / agent / skill_center / cli / main）
- SkillCenter 一体化管理：SQLite 持久化 + skills/ 目录同步 + 内存缓存 + hash 变更检测
- 运行时技能热更新：修改技能后无需重启 Agent 服务
- CLI 管理入口：python -m src.skill_center add/update/delete/list
- Agent 请求级重实例化：每次用户输入重新 build_agent，自动携带最新技能

**Non-Goals:**
- 不涉及技能远程拉取（仅本地 SQLite）
- 不涉及自定义 tool 注册（沿用 DeepAgents 内置工具集）
- 不涉及权限管理
- 不涉及 Web 服务封装

## Decisions

| 决策 | 选型 | 理由 |
|------|------|------|
| 技能格式 | YAML frontmatter + Markdown body | 与 DeepAgents SkillsMiddleware 兼容；name/description/version/triggers 标准化元数据 |
| 持久化方案 | SQLite（内置库，零依赖） | 无需引入外部 DB，Python 内置 sqlite3 即满足需求 |
| 目录同步 | CRUD 操作先写 SQLite，再写 skills/{name}/SKILL.md | skills/ 目录保持最新，SkillsMiddleware 可直接扫描 |
| 变更检测 | SQLite skill_meta 表维护全局版本号，每次 CRUD +1 | 一次 SELECT 即可感知变更，零文件 IO，比 MD5 hash 直观高效 |
| 热更新机制 | decorate_state() 判 hash → pop skills_metadata → SkillsMiddleware 重读 | 不 hack 框架，利用已有 SkillsMiddleware 缓存机制 |
| Agent 构建 | 每次请求 create_deep_agent() | 确保最新的 system prompt 和技能内容；MemorySaver 通过 thread_id 保持上下文连续性 |
| 管理入口 | `python -m src.skill_center <action>` | Python 标准做法，无需额外 CLI 框架 |
| 数据库位置 | 项目根目录 `skills.db` | 简单直观，gitignore 忽略 |

## Risks / Trade-offs

- **性能风险**：每次请求重新实例化 Agent（create_deep_agent）有开销 → 实测 demo 场景瞬时完成，可接受；如未来需要高性能，可引入 Agent 池化
- **SQLite 并发**：单用户场景无并发问题，多进程使用时 SQLite 需注意写入锁 → demo 阶段不涉及
- **skills/ 目录与 SQLite 的一致性**：CRUD 操作通过事务保证写 SQLite + 写磁盘原子性；直接手动修改 skills/ 目录会绕过注册中心 → 管理入口是唯一推荐方式
- **skills_metadata 在 state 中的传递**：pop 操作需在每次 agent.invoke 前完成 → 封装在 cli.py 主循环中，逻辑清晰

## Migration Plan

1. 创建新模块文件，保留 `agent_demo.py` 作为参考
2. 实现 SkillCenter（含 SQLite 表结构、CRUD、hash 检测）
3. 实现 config / model / agent 模块
4. 实现 cli / main 入口
5. 验证通过后删除 `agent_demo.py`