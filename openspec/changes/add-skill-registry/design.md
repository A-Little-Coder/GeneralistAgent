## Context

中控 Agent 在规划阶段需要知道当前可用的全部 Skill / Teammate（含名称、描述、入参、依赖、调用方式），在执行阶段又需要把它们转成 deepagents 能理解的 sub_agent / tool。如果手写注册表，每加一个 Skill 都要改三处（文档、注册表、deepagents 入参），容易脱节。OpenSpec 项目中所有 SKILL 应"目录即注册"。开发期还需要"改 SKILL.md 不重启服务"以缩短迭代循环。

## Goals / Non-Goals

**Goals:**
- 固化 SKILL 目录约定与 `SKILL.md` 模板，让新 Skill 接入只需新增一个目录
- 启动期扫描自动注册，校验 schema、唯一名、依赖闭合
- 生成 deepagents 适配层，把 SkillSpec 转成 `create_deep_agent(subagents=..., tools=...)` 的入参
- 开发期支持 watchdog 热加载，线上默认关闭
- 暴露摘要表给规划层做 few-shot 召回

**Non-Goals:**
- 不实现 Skill 的具体业务逻辑（在 `add-teammate-protocol` 与各 Skill 自身）
- 不实现案例召回（在 `add-orchestrator-planner`）
- 不绑死 deepagents 具体版本，通过适配层隔离

## Decisions

### 决策 1：SKILL 目录约定

```
skills/
├── _common/                    # 中控自己用的公共 SKILL（非 Teammate）
│   ├── ask_back/
│   │   └── SKILL.md
│   └── plan_recall/
│       └── SKILL.md
└── teammates/                  # Teammate 套壳 SKILL
    ├── ask_data/
    │   ├── SKILL.md            # 必需
    │   ├── manifest.yaml       # 可选：补充配置（endpoint、auth）
    │   ├── client.py           # 可选：调用旧 Agent 服务
    │   ├── prompts/
    │   │   └── system.md       # 可选
    │   └── examples.json       # 可选：few-shot
    └── ...
```

- 一个 SKILL = 一个目录 = 一份 `SKILL.md`
- 类型由 `SKILL.md` frontmatter 的 `type` 决定（不依赖父目录路径，但路径必须落在 `skills/_common/` 或 `skills/teammates/` 下）

### 决策 2：SKILL.md 模板（强 schema）

```markdown
---
name: ask_data                   # 全局唯一，kebab-case
description: |
  调用问数 Agent，将自然语言问题转 SQL 并返回数据结果。
type: teammate                   # teammate | common | sub_agent
runtime: http                    # mcp | http | local
endpoint: ${ASK_DATA_URL}        # runtime=http/mcp 时必填，支持 env 插值
depends_on: []                   # 依赖其他 SKILL 的 name 列表
inputs:
  - name: question
    type: str
    required: true
outputs:
  - name: data
    type: dataframe
triggers:                        # 规划层做 BM25 召回时用
  - 查询...库存
  - ...销量是多少
max_retries: 2                   # 可选；缺省读全局默认 1
timeout_s: 30                    # 可选
---

## 何时使用
... 自由文本，给 LLM 看 ...

## 调用方式
... 可包含 client.py 函数签名说明 ...
```

- frontmatter 通过 `pydantic` 模型 `SkillSpec` 校验
- 正文（`何时使用` / `调用方式`）作为 LLM 提示词的"长描述"被规划层使用

### 决策 3：扫描与注册流程

```
SkillScanner.scan(root="skills/")
   │
   ├── glob "**/SKILL.md"
   ├── 解析 YAML frontmatter + 正文 → SkillSpec
   ├── 路径前缀校验（必须在 _common/ 或 teammates/ 下）
   ├── name 唯一性校验
   ├── depends_on 闭合校验（所有依赖必须在本批次内）
   └── 返回 list[SkillSpec]

SkillRegistry.bootstrap(specs)
   │
   ├── self._by_name: dict[str, SkillSpec] = {...}
   ├── self._summary_table: list[SkillSummary]   # 给规划层
   └── 写出 skills_manifest.json（供 LangSmith 关联）
```

- `SkillRegistry` 是进程内单例，注册一次即只读（除非 hot reload 触发 `replace_one`）
- `SkillSummary = (name, description, type, inputs摘要, triggers)`，规划层只看这个，避免过长 prompt

### 决策 4：deepagents 适配层

deepagents 0.x 的 `create_deep_agent(subagents=[...], tools=[...])` 接受：
- `subagents`：list of dict，含 `name` / `description` / `prompt` / `tools`
- `tools`：list of LangChain `BaseTool`

适配规则：

| SkillSpec.type | 适配为 |
|---|---|
| `teammate` | deepagents `subagents` 一项 + 注入 `raise_question` 工具 + 注入 client 工具 |
| `common` | LangChain `BaseTool`（即可作为顶层 tool 使用） |
| `sub_agent` | deepagents `subagents` 一项（轻载、无外部 client） |

- 适配代码集中在 `chatbi/infra/skill_registry/deepagents_adapter.py`，对外暴露 `to_deepagents_kwargs(registry) -> dict`
- 当 deepagents 版本升级 API 变化，只改这一个文件

### 决策 5：watchdog 热加载

- 默认关闭。仅当 `os.environ["SKILL_HOT_RELOAD"] == "true"` 才启用
- `Observer` 监听 `skills/` 递归
- `SkillFileHandler.on_modified / on_created / on_deleted` 触发：
  - debounce 500ms（同一路径多次事件合并）
  - 后缀白名单：仅 `SKILL.md` 触发；`.swp` / `~` 等忽略
  - 文件大小连续 2 次稳定（间隔 100ms）才视作写完
- `created` / `modified` → `registry.upsert(spec)`；`deleted` → `registry.remove(name)`
- 关键约束：**规划运行中（持有 plan_run lock）禁止热替换 deepagents kwargs**，仅替换 `_by_name`，避免规划进行时 schema 漂移导致执行找不到工具
  - 实现：`registry.replace_one()` 仅替换 `_by_name`；`to_deepagents_kwargs()` 在每次 plan_run 启动时重新计算

### 决策 6：依赖闭合 vs 启动期失败策略

- 依赖闭合校验失败：启动直接报错并退出（避免后续规划在线上崩）
- 单个 SKILL.md 解析失败：报错列出所有失败项，整体启动失败
- 重名：报错并列出冲突路径
- 理由：注册是启动期一次性动作，宁可启动失败，不要运行时崩

## Risks / Trade-offs

- [Risk] watchdog 在 Windows 网络盘上事件不稳定 → Mitigation：要求在本地磁盘运行；远程开发用 polling observer 兜底
- [Risk] `SKILL.md` frontmatter 写错（YAML 缩进）启动直接挂 → Mitigation：错误信息中文输出，列出文件路径与具体字段
- [Risk] deepagents API 升级导致适配层失效 → Mitigation：适配层内部加一个 `DEEPAGENTS_VERSION_TESTED` 常量，启动时与已安装版本比对，差异时打 WARNING
- [Trade-off] hot reload 不在线上启用 = 改 SKILL 必须发版；可接受，因为线上 SKILL 改动天然走 PR

## Migration Plan

- 新建项目，无迁移
- 后续若引入新的 runtime（如 grpc），在 `SkillSpec` 的 `runtime` 字段加枚举值，并在适配层加分支

## Open Questions

- 是否允许 SKILL.md 嵌套子目录（如 `skills/teammates/ask_data/v2/SKILL.md`）做版本？暂不允许，先扁平
- `manifest.yaml` 的字段是否要一并写进 `SKILL.md`？为减少初期复杂度，本 change 先不要求 `manifest.yaml`，所有字段都在 frontmatter
