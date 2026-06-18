## Why

当前 `agent_demo.py` 是单文件架构，所有逻辑耦合在一起。同时 Agent 缺乏技能管理体系——SKILL.md 仅在 session 启动时加载一次，运行中变更技能只能重启服务。需要引入标准化 Skill 体系，实现运行时技能热更新。

## What Changes

- **重构** 单文件 `agent_demo.py` 拆分为多模块：`config.py`、`model.py`、`agent.py`、`skill_center.py`、`cli.py`、`main.py`
- **新增** `SkillCenter` 统一管理技能生命周期（SQLite 持久化 + 文件系统同步 + 内存缓存 + 变更检测）
- **新增** 命令行管理接口 `python -m src.skill_center`（add/update/delete/list）
- **保留** DeepAgents `SkillsMiddleware` 作为技能加载机制，通过控制 `skills_metadata` 状态键触发热重载
- **修改** `build_agent()` 每次请求重新实例化 Agent，从注册中心获取最新技能状态

## Capabilities

### New Capabilities
- `skill-center`: 标准化 Skill 管理体系，包含 SQLite 持久化、目录同步、版本 hash 变更检测、decorate_state() 接口

### Modified Capabilities
- `deep-agent-demo`: 从单文件架构重构为多模块架构；新增请求级 Agent 重实例化；集成 SkillCenter 实现技能热更新

## Impact

- `src/agent_demo.py` — **删除**，功能分散到新模块
- `src/config.py` — **新增**，配置加载与校验
- `src/model.py` — **新增**，模型初始化
- `src/agent.py` — **新增**，Agent 构建
- `src/skill_center.py` — **新增**，Skill 管理中心（含 CLI 入口）
- `src/cli.py` — **新增**，交互主循环
- `src/main.py` — **新增**，入口
- `src/__init__.py` — **新增**，包标记
- `skills.db` — **新增**，SQLite 数据库文件
- `.env` — **无变化**