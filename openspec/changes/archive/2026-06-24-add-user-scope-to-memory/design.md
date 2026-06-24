## Context

`add-memory-persistence` 已经把 Leader 的对话历史持久化到 `memory/leader.db`（AsyncSqliteSaver）+ 元数据到 `memory/sessions.json`（SessionManager）。但这一层的隐式假设是"进程内只有一个用户"：

- `sessions.json` 的 `sessions` 列表没有 owner，`current` 也是全局唯一
- `leader.db` 的 `thread_id` 就是 `session-X`，跨用户必然撞名
- CLI 没有 user 概念

要为后续 API 化做准备，**user_id 必须作为一等公民提前进入数据模型**。但本次 change 是**只改单机 CLI** —— API 协议、并发、鉴权全部留给后续 change。

约束（已与用户确认）：
1. CLI 启动时 `input()` 读 user_id；运行中支持 `/user <id>` 切换
2. 旧数据要迁移：sessions.json 归到 `users.default`，leader.db 中无冒号的 thread_id 改名为 `default:<原id>`
3. session_id 跨 user 允许同名（alice 的 session-1 ≠ bob 的 session-1）
4. teammate_id 不加 user 前缀（Teammate 每轮焚毁，无串台风险）
5. Teammate / Runner / TeamManager / 编排工具集**完全不动**

## Goals / Non-Goals

**Goals:**

- CLI 启动绑 user_id；运行中可切换；提示符显示 `user/session`
- `thread_id = "{user_id}:{session_id}"`，多 user 在 leader.db 互不可见
- 旧 sessions.json / 旧 leader.db 自动一次性迁移到 `default` user 下，幂等
- session_id 跨 user 可同名，不影响隔离
- 测试覆盖：user 隔离、迁移、命令切换、并发同名 session

**Non-Goals:**

- 不做 API（FastAPI / SSE / WebSocket）—— 留给下一个 change
- 不做鉴权 / 多租户授权
- 不做并发保护（per-user lock 等）—— CLI 仍是单线程串行模型
- 不动 Teammate 维度（teammate_id / spawn / cleanup）
- 不改教学 demo（learn/05/）

## Decisions

### D1. user_id 注入入口：CLI `input()`，env 兜底

启动流程：

```python
async def repl(...):
    print(_BANNER)
    user_id = _prompt_user_id()             # input("请输入 user_id (回车默认 default): ")
    print(f"当前 user: {user_id}")
    ...
```

不传入命令行参数。回车视为 `default`。

**Why**：
- CLI 现成有 `_ainput` 异步包装
- 后续 API 化时替换为 header 透传，入口集中可替
- 命令行参数可作 advanced 用法后续加，不在本 change 范围

**Alternatives**：
- `--user` 命令行参数 → 否；CLI 启动只一次，input 更直观
- 环境变量 `USER_ID` → 否；与 .env 配置混淆，且 CLI 单机切换不方便

### D2. SessionManager 状态化 —— current_user_id

`SessionManager` 内部持有"当前用户" + 完整的 `users` 数据结构：

```python
class SessionManager:
    _data: dict[str, _UserBucket]           # user_id -> {current, sessions}
    _current_user_id: str

    def switch_user(self, user_id: str) -> None: ...
    def list(self) -> list[Session]:        # 隐式作用于 current user
    def new(self) -> Session: ...
    def bootstrap(self) -> Session:         # 用 current_user
```

所有公共方法不显式传 user_id —— SessionManager 始终知道"当前是谁"。

**Why**：
- 调用方（CLI）写起来干净，不必每个方法都传一遍 user_id
- 与"运行中 /user 切换"语义一致：切换后所有后续操作落到新 user
- API 化时 SessionManager 不直接共享 —— 每个 HTTP 请求构造自己的 view（或换实现），所以这层状态化不阻碍未来

**Alternatives**：
- 所有方法显式传 user_id（无状态）→ 否；调用方代码到处带 user_id 冗余
- 拆 `UserManager` + `SessionManager`（前者管 users，后者无状态）→ 过度设计，CLI 不需要

### D3. sessions.json 新格式

```json
{
  "users": {
    "alice": {
      "current": "session-1",
      "sessions": [
        {"id": "session-1", "title": "...", "created_at": "...", "last_active_at": "..."}
      ]
    },
    "default": {
      "current": "session-1",
      "sessions": [...]
    }
  }
}
```

`current_user_id` **不持久化** —— 每次启动都由 CLI 输入决定。

**Why**：
- "当前 user"是会话层概念，不是用户长期偏好
- 不持久化避免"上次 alice，下次启动默认还是 alice"的隐式行为

**Alternatives**：
- 同时持久化 `current_user`，CLI 启动时 `input("user [上次=alice]: ")` 提示默认值 → 多用户场景反而易出错，砍掉

### D4. thread_id 拼接规则

```python
thread_id = f"{user_id}:{session_id}"        # 例 "alice:session-1"
```

冒号是唯一分隔符。约束：
- user_id 不允许含冒号（启动时校验，含冒号则报错让重输）
- session_id 由系统生成（`session-N`），天然不含冒号

CLI 在两处构造 thread_id：
1. `agent.astream(config={"configurable": {"thread_id": composed}})`
2. `LeaderStore.purge(composed)`（`/delete` 时）

**Why**：
- 字符串拼接 + 唯一分隔符，最朴素
- 后续做迁移 / 调试时直接 `SELECT thread_id LIKE 'alice:%'` 就能筛 alice 的全部历史
- 不改 LeaderStore / AsyncSqliteSaver —— thread_id 对它们就是字符串

**Alternatives**：
- LangGraph 的 `checkpoint_ns`：把 user_id 放 ns 字段 → 是更"标准"的方案，但要改 `LeaderStore.purge` / 查询过滤等多处；本 change 范围内不值得，作为后续优化候选

### D5. 旧数据迁移：启动时一次性

启动顺序：

```
LeaderStore.create() → setup()
   │
   ├─ migrate_legacy_thread_ids()        # 把 leader.db 里无冒号 thread_id 改名
   │
SessionManager(...)
   │
   └─ _load() 中检测旧格式 → 自动迁移到 users.default → _save()
```

两处迁移都是**幂等的**：再次启动看到的就是新格式，不会重复迁。

**Why**：
- 迁移在启动时透明完成，用户无感
- 失败可恢复：迁移用 SQL 事务 + JSON 原子写
- 单次迁移成本远小于"用户手动维护两份格式"

**实现细节**：

```sql
-- migrate_legacy_thread_ids 伪代码
BEGIN;
UPDATE checkpoints SET thread_id = 'default:' || thread_id
  WHERE thread_id NOT LIKE '%:%';
UPDATE writes SET thread_id = 'default:' || thread_id
  WHERE thread_id NOT LIKE '%:%';
COMMIT;
```

对 sessions.json：检测顶层无 `users` 字段就视为旧格式：
```python
if "users" not in data and "sessions" in data:
    data = {"users": {"default": {"current": data.get("current"), "sessions": data["sessions"]}}}
```

### D6. CLI 提示符 / 命令

```
请输入 user_id (回车默认 default): alice
当前 user: alice
当前会话：session-1  (未命名)

[alice/session-1] 你 > 你好
...

[alice/session-1] 你 > /user bob
✓ 切换到 user 'bob'
当前会话：session-1  (未命名)

[bob/session-1] 你 > ...
```

`/user` 命令：
- 切换后 sessions 列表跟着切（看到 bob 的 sessions，不是 alice 的）
- bob 若没有任何 session → 自动 bootstrap session-1
- bob 切回 alice 再切回来 —— 各 user 的 current 各自保留

`/help` 新增一行说明 `/user`。

### D7. teammate_id 维持原状

`teammate_id = format_agent_id(name, team_name)`（不含 user）。

**Why**：
- Teammate 每轮 cleanup_spawned_in_turn 焚毁，下一轮无论谁触发都是全新 MemorySaver
- 不会有跨 user 的 Teammate 状态污染
- 加 user_id 反而需要改 Runner / TeamManager / 编排工具，违反"不动 Teammate 维度"约束

唯一的考虑：**并发**。如果同一时刻 alice 和 bob 都触发了 spawn 一个名叫 `chatbi_proxy` 的 Teammate，会因为同名冲突。但 CLI 是单线程串行 REPL —— **本 change 不存在并发场景**。后续 API 化时连同并发模型一起重新设计。

## Risks / Trade-offs

- [迁移失败导致 leader.db 损坏] → 迁移逻辑用 SQL 事务（BEGIN/COMMIT），失败回滚；额外提供 `--no-migrate` 兜底（不在本 change 范围；如真出问题用户可手 SQL）
- [user_id 含冒号 → thread_id 解析歧义] → 启动 input 时校验，含 `:` 重新输入
- [user 切换时本轮可能正有 Teammate 在跑] → `/user` 命令前先调 `cleanup_spawned_in_turn`（与每轮请求边界一致）；正常情况下 user 切换发生在 turn 之间，不会进行到一半
- [sessions.json 单文件并发写问题] → CLI 单线程不并发，N/A；将来 API 化要单独解决
- [用户每次启动都要输一遍 user_id] → 可接受；后续可加 `~/.generalist/last_user` 之类便利，不在本 change
- [/user 切到从未存在的 user_id] → 自动建空 bucket + bootstrap session-1，不报错（保持"低摩擦"）

## Migration Plan

1. 实现 `src/persistence/user_migration.py`（含 `migrate_legacy_thread_ids` SQL 函数 + sessions.json 迁移逻辑）
2. 改 `SessionManager` 的 `_load` / `_save` 支持新格式 + 自动迁移
3. 改 `LeaderStore.setup` 末尾调一次 `migrate_legacy_thread_ids`
4. 改 `cli.py`：启动输入 user_id；`/user` 命令；提示符
5. 改测试 + 加新测试
6. 文档 / 注释更新

无回滚需求：迁移幂等；若新 change 有缺陷可 git revert，因为迁移已经把旧数据格式改了，**需配套提供反向迁移脚本**（视 review 决定，本 change 不强制做）。

## Open Questions

- **CLI 启动时 input user_id 失败（Ctrl+C / EOF）怎么办？** → 当作"用户取消启动"，直接 `sys.exit(0)`
- **/user 命令是否需要二次确认？** → 否；与 /switch（切 session）保持一致，无确认
- **空 user_id 是否合法？** → 不合法，input 校验 `strip() == ""` 时回退 default
- **后续 API 是否仍用同一个 SessionManager / LeaderStore？** → 留给下一个 change（API change）评估，**不影响**本 change 的设计
