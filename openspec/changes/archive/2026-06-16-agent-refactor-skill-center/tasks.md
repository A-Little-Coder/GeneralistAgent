## 1. 基础模块拆分

- [x] 1.1 创建 `src/__init__.py` 包标记，创建 `src/config.py`（从 agent_demo.py 提取 load_config）
- [x] 1.2 创建 `src/model.py`（从 agent_demo.py 提取 init_model）
- [x] 1.3 创建 `src/agent.py`（build_agent，每次请求重新 create_deep_agent，使用 LocalShellBackend）

## 2. SkillCenter 实现

- [x] 2.1 创建 `src/skill_center.py` 核心类，实现 SQLite 表结构创建、CRUD 方法
- [x] 2.2 实现 skills/ 目录同步（add→写 SKILL.md，update→覆盖，delete→删除目录）
- [x] 2.3 改为数据库版本号变更检测：加 skill_meta 表 + decorate_state 用 SELECT 比版本号
- [x] 2.4 实现 CLI 管理入口（python -m src.skill_center add/update/delete/list）

## 3. CLI 主循环与集成

- [x] 3.1 创建 `src/cli.py`（消息打印 + 交互循环），集成 SkillCenter.decorate_state()
- [x] 3.2 创建 `src/main.py` 入口，组装所有模块
- [x] 3.3 创建示例技能目录 `skills/general/SKILL.md`

## 4. 验证与清理

- [x] 4.1 运行 `python src/main.py` 验证基础对话和工具调用
- [x] 4.2 运行中新增/修改 skill，验证热更新生效
- [x] 4.3 验证 `python -m src.skill_center list` 等管理命令
- [x] 4.4 验证通过后删除 `src/agent_demo.py`

## 5. 装饰器改进与技能补充

- [x] 5.1 重构 decorate_state 为全局版本号方案（skill_meta 表，每次 CRUD 自动 +1）
- [x] 5.2 通过 SkillCenter 添加 calculator 技能

## 6. 远程存储重构与 FastAPI 服务

- [x] 6.1 创建 `src/skill_db.py` → `src/skills/db.py` 公共抽象层（SkillRepository）
- [x] 6.2 创建 `src/skill_server.py` → `src/skills/server.py` FastAPI 服务
- [x] 6.3 改造 `src/skill_center.py` → `src/skills/center.py`：直连远程 DB 检测 + 全量同步到本地 skills/
- [x] 6.4 创建 `tests/test_skill_center.py`（18 个测试用例）
- [x] 6.5 端到端验证：远程新增技能 → 热同步 → Agent 感知变更

## 7. src 代码分层归类

- [x] 7.1 创建 `src/core/`：配置、模型、Agent
- [x] 7.2 创建 `src/skills/`：技能 DB、中心、FastAPI 服务
- [x] 7.3 创建 `src/interface/`：CLI 交互层
- [x] 7.4 更新所有 import 路径，删除根层旧文件
- [x] 7.5 修复路径解析（config.py 目录深度变化）
- [x] 7.6 18 个测试 + 端到端验证通过