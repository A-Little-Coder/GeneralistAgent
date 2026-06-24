## 1. 持久化层

- [ ] 1.1 创建 `src/persistence/user_migration.py`：含 `migrate_legacy_thread_ids(conn)` 异步函数（事务 + 幂等 SQL）
- [ ] 1.2 改 `src/persistence/leader_store.py`：`setup()` 末尾调一次 `migrate_legacy_thread_ids`；新增异常吞掉但打日志
- [ ] 1.3 改 `src/persistence/session_manager.py` 数据结构：内部存 `dict[user_id, _UserBucket]` + `current_user_id` 字段
- [ ] 1.4 SessionManager 公共方法保持原签名，全部隐式作用于 `current_user_id`
- [ ] 1.5 SessionManager 新增 `switch_user(user_id: str)` 方法：切换 current_user_id，必要时为新 user bootstrap
- [ ] 1.6 SessionManager 新增 `current_user_id` 属性 + setter / `users()` 方法（列出已存在 user_id，仅调试用）
- [ ] 1.7 SessionManager `_load` 检测旧格式（无 `users` 键）→ 包到 `users.default` 下 → `_save` 立刻覆写
- [ ] 1.8 SessionManager 不持久化 `current_user_id`（每次启动由 CLI 决定）
- [ ] 1.9 SessionManager 暴露 `compose_thread_id(session_id) -> str` 助手：返回 `f"{current_user_id}:{session_id}"`

## 2. CLI 集成

- [ ] 2.1 改 `src/interface/cli.py`：`repl()` 在 banner 后调 `_prompt_user_id()` 读 user_id
- [ ] 2.2 `_prompt_user_id()` 实现：循环 `_ainput`、回车 → "default"、含冒号拒绝、Ctrl+C/EOF → sys.exit(0)
- [ ] 2.3 启动后 `sm.switch_user(user_id)` + `sm.bootstrap()`
- [ ] 2.4 `_run_turn` 与 `_handle_command(/delete)` 中所有 thread_id 改为 `sm.compose_thread_id(session.id)`
- [ ] 2.5 提示符改为 `[{user}/{session}] 你 >`
- [ ] 2.6 启动横幅改为显示当前 user
- [ ] 2.7 新增 `/user <user_id>` 命令：先 `cleanup_spawned_in_turn`，再 `sm.switch_user`，再打印新 session 信息
- [ ] 2.8 `/help` 文本加 `/user` 说明

## 3. 测试

- [ ] 3.1 改造 `tests/test_session_manager.py`：所有 bootstrap / new / list / switch / delete / rename 用例覆盖 `current_user_id="default"` 路径
- [ ] 3.2 新增 `tests/test_user_scope.py`：
  - test_switch_user_creates_bucket：新 user 自动 bootstrap session-1
  - test_users_are_isolated：alice / bob 各自 sessions 互不可见
  - test_same_session_id_across_users：alice.session-1 ≠ bob.session-1
  - test_compose_thread_id：拼接结果正确
- [ ] 3.3 新增 `tests/test_user_migration.py`：
  - test_legacy_sessions_json_migrated：旧 sessions.json 加载后变成新格式且落盘
  - test_already_new_format_no_op：新格式重启不动
  - test_legacy_leader_db_thread_ids_migrated：写入 `session-1` 后过迁移变 `default:session-1`
  - test_leader_db_migration_idempotent：迁过的库再启动不动
  - test_leader_db_migration_transaction：模拟 SQL 失败回滚（用 monkeypatch 强制 raise）
- [ ] 3.4 改造 `tests/test_leader_persistence.py`：测试用的 thread_id 改为含 `:` 形式（验证仍可写读）
- [ ] 3.5 改造 `tests/test_streaming.py` 中 `_run_turn` 相关：thread_id 用 compose 后的形式
- [ ] 3.6 全量回归 `python -m pytest tests/ -v`

## 4. 文档与教学

- [ ] 4.1 `learn/05-memory-persistence/README.md` 末尾加一节"扩展：user_id 维度"，链接到本 change 的 spec
- [ ] 4.2 不新增 demo（user_id 是项目级便利，不属于 LangGraph 核心）

## 5. 验收

- [ ] 5.1 `openspec validate add-user-scope-to-memory --strict` 通过
- [ ] 5.2 手动验收 - 单 user：启动输入 alice → 对话 → 退出 → 重启输入 alice → 历史还在
- [ ] 5.3 手动验收 - 多 user 隔离：alice 写 "我叫张三"；切 bob 写 "我叫李四"；切回 alice 询问 → 答张三
- [ ] 5.4 手动验收 - 同名 session 跨 user 独立：alice/session-1 与 bob/session-1 互不污染
- [ ] 5.5 手动验收 - 旧数据迁移：手工往 leader.db 写一行 `thread_id='legacy-x'` + sessions.json 用旧格式 → 重启 → 校验都已带 `default:` 前缀 / 归到 default 桶
- [ ] 5.6 手动验收 - /user 切换：alice → bob，bob 是新 user 自动 bootstrap session-1；切到 charlie → 同样自动 bootstrap
- [ ] 5.7 手动验收 - /user 切换前焚毁本轮 Teammate：观察日志 cleanup_spawned_in_turn 被调
