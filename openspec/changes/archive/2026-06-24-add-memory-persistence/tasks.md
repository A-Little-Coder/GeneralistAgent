## 1. 依赖与目录

- [x] 1.1 安装 `langgraph-checkpoint-sqlite`（清华源）并写入 requirements.txt
- [x] 1.2 `.gitignore` 增加 `memory/` 与 `learn/__pycache__/`
- [x] 1.3 创建 `src/persistence/__init__.py` 子包

## 2. 持久化层

- [x] 2.1 实现 `src/persistence/leader_store.py`：封装 `SqliteSaver`（路径 `memory/leader.db`），暴露 `get_checkpointer()`、`purge(session_id)`、`close()`
- [x] 2.2 实现 `src/persistence/session_manager.py`：`Session` dataclass、`SessionManager` 类（load / save 原子写、new / list / switch / delete / rename / bootstrap / set_title_if_empty）
- [x] 2.3 实现 `src/persistence/tool_truncate.py`：`truncate_for_persist(content, limit=None)` + 读环境变量 `TOOL_PERSIST_MAX_CHARS`（默认 4000）

## 3. Agent 工厂改造

- [x] 3.1 修改 `src/core/agent.py`：`build_agent(..., checkpointer=None)` 参数化；为 None 时回退到 `MemorySaver()` 保持旧测试兼容
- [x] 3.2 在 `build_agent` 中显式校验：传入的 checkpointer 必须是 `BaseCheckpointSaver` 子类，否则抛 TypeError

## 4. CLI 集成

- [x] 4.1 修改 `src/interface/cli.py`：repl 中初始化 `LeaderStore` + `SessionManager.bootstrap()`
- [x] 4.2 删除 `rebuild_state` 与 `_run_turn` 返回 state 的逻辑；改为每轮只发 `{"messages": [HumanMessage(user_input)]}` 给 astream
- [x] 4.3 实现命令解析层：`/new` `/sessions` `/switch` `/delete` `/title` `/help`（在 `_repl_loop` 入口识别 `/` 前缀路由）
- [x] 4.4 `/delete` 增加 `y/N` 二次确认（默认 No）
- [x] 4.5 每轮把 user_input 喂给 `SessionManager.set_title_if_empty(current, user_input)`
- [x] 4.6 在每轮 `finally` 调 `team_manager.cleanup_spawned_in_turn()`
- [x] 4.7 删除 `_SYSTEM_PROMPT` 中"一个查询请求只需要建 **一个** Teammate"那一行
- [x] 4.8 CLI 启动横幅 / 提示符显示当前 session 名

## 5. Runner / TeamManager 改造

- [x] 5.1 修改 `src/orchestration/runner.py`：`_loop` 首次启动时调一次 `build_agent_for_prompt()` 缓存到 `self._agent`；`_run_one_turn` 复用缓存
- [x] 5.2 Runner 内部 thread_id 不变（teammate_id），但每个 Teammate 用独立 MemorySaver（验证多 Teammate 互不可见）
- [x] 5.3 修改 `src/orchestration/team.py`：`TeamManager` 增加 `_spawned_this_turn: set[str]` 与方法 `cleanup_spawned_in_turn()`
- [x] 5.4 `spawn_teammate` 内部将 teammate_id 加入 `_spawned_this_turn`
- [x] 5.5 `cleanup_spawned_in_turn` 异常吞掉但打日志，不阻塞 REPL 下一轮

## 6. 工具返回截断

- [x] 6.1 在 `src/orchestration/tools.py` 中所有 dict 返回的 string 长字段（content / reason / 结果摘要）经 `truncate_for_persist` 处理
- [x] 6.2 NL2SQL 等代理工具的 ToolMessage 返回若包含大体量结果，由 `proxy_tools` 自行调用 `truncate_for_persist` 截断

## 7. 测试

- [x] 7.1 `tests/test_leader_persistence.py`：模拟"写入 → 关 store → 重新打开 → 历史恢复"流程；覆盖 `purge`
- [x] 7.2 `tests/test_session_manager.py`：bootstrap 空、bootstrap 已有、new、list、switch、delete current、delete other、set_title_if_empty 长短两种、rename
- [x] 7.3 `tests/test_teammate_memory.py`：Runner 同一请求内被唤起两次，第二次能引用第一次的内容；不同 Teammate 互不可见
- [x] 7.4 `tests/test_cleanup_turn.py`：mock spawn 两个 Teammate，调 cleanup_spawned_in_turn 后两个 Runner.task.done() 为 True；下一轮 set 为空
- [x] 7.5 `tests/test_tool_truncate.py`：阈值边界 / 中文字符 / 环境变量覆盖
- [x] 7.6 全量回归 `python -m pytest tests/ -v`，目标全部通过

## 8. 教学产出 learn/05-memory-persistence/

- [x] 8.1 `README.md`：方案总览 + 双层记忆边界图 + 阅读顺序
- [x] 8.2 `01-memory-saver/README.md` + `demo_memory_saver.py`：构 graph、用 MemorySaver、多轮对话能记住名字
- [x] 8.3 `02-sqlite-saver/README.md` + `demo_sqlite_resume.py`：跑一次保存历史 → 第二次进程恢复
- [x] 8.4 `03-thread-id-and-sessions/README.md` + `demo_sessions.py`：同库不同 thread_id 互不串台、模拟 /switch
- [x] 8.5 `04-teammate-vs-leader/README.md` + `demo_two_tier_memory.py`：演示 Leader 用 SqliteSaver、Teammate 用 MemorySaver 的隔离效果
- [x] 8.6 `05-cleanup-and-lifecycle/README.md` + `demo_cleanup.py`：观察 Teammate 创建 → 多次唤起 → cleanup 后内存释放
- [x] 8.7 教学 demo 全部可独立 `python learn/05-memory-persistence/xx/yy.py` 跑通；不 import `src/`

## 9. 验收

- [x] 9.1 手动验收：CLI 启动 → 说话 → 退出 → 重新启动 → 历史还在
- [x] 9.2 手动验收：`/new` 创建 session 后首条消息触发标题；`/sessions` 看到列表
- [x] 9.3 手动验收：`/delete <current>` 后能正确切到剩余 session 或新建 session-1
- [x] 9.4 手动验收：同一请求内让 Leader 给同名 Teammate 派两次任务，第二次能引用第一次的 NL2SQL 结果
- [x] 9.5 手动验收：一轮结束后 Teammate 真的被焚毁（用 team_list 查应当为空）
- [x] 9.6 `openspec validate add-memory-persistence --strict` 通过
