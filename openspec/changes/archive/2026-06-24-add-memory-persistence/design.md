## Context

GeneralistAgent 当前的"记忆"由两条并行但都不持久的链路拼起来：

1. **Leader 端**：`src/core/agent.py` 硬编码 `MemorySaver()`，每次 `build_agent` 都换新 saver；`src/interface/cli.py` 通过 `rebuild_state` 手动把流式收集到的 messages 追加进 state 维持当 turn 上下文 —— 但 CLI 一退出，整段历史归零。
2. **Teammate 端**：`src/orchestration/runner.py` 每个 turn 都 `build_agent_for_prompt()` 再造 Agent、再造 MemorySaver、state 永远以 `[HumanMessage(prompt)]` 起步。这意味着 Leader 在同一用户请求内多次给 Teammate 派任务 / 发消息，Teammate 之间是没有任何上下文的，Leader 必须每次重发完整背景。

两端都需要改：Leader 要从"进程内 RAM"升级为"跨进程 SQLite"；Teammate 要从"每 turn 重建"升级为"请求内累积 + 请求结束焚毁"。两层记忆的**生命周期是错位的**（Leader > Session > 请求 > Teammate），所以放在同一个 change 里一起设计，避免后续打补丁。

约束（来自 CLAUDE.md / 已确认的讨论结论）：

- Leader 的 SKILL 必须保留热更新；Teammate 的 SKILL 在 spawn 时冻结即可（请求内 SKILL 不会变）。
- 不引入外部数据库；只用 SQLite + JSON 文件。
- 所有路径、命令、注释默认中文。
- 不能让 Leader 看见外部服务的 base_url / token —— 持久化层只触碰 messages，不触碰 ProxyServiceConfig。

## Goals / Non-Goals

**Goals:**

- Leader 跨进程恢复完整对话历史（类豆包 `/new` 切话题模型）。
- Teammate 在一次用户请求内多次唤起共享记忆（X2 语义）；turn 结束统一焚毁。
- 移除 `cli.py` 的手动 `rebuild_state`，依赖 LangGraph 官方 checkpointer 机制。
- 工具返回入库前可截断，避免 leader.db 被异常巨大的 SQL 结果撑爆。
- 产出可独立运行的教学 demo（learn/05-memory-persistence/）。

**Non-Goals:**

- 不实现跨进程的 Teammate 持久化（明确决策：Teammate = RAM only）。
- 不接 LangGraph SummarizationMiddleware 做自动摘要（Q2=a：让模型 context window 自行处理）。
- 不做 P2 trace 落盘（开发完成后若有需要再开 change）。
- 不实现并发多会话（同一时刻仅一个 current session；并发请求是后续话题）。
- 不改造现有 `skills.db`（保持独立，记忆库放新文件 `memory/leader.db`）。

## Decisions

### D1. Leader 用 `AsyncSqliteSaver`，Teammate 用 `MemorySaver`

**选择**：`langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver`（Leader，异步）+ `langgraph.checkpoint.memory.MemorySaver`（Teammate，同步）。

**Why**：

- LangGraph 官方提供的 checkpointer 直接吃掉 messages 持久化和恢复，无须自定义表。
- 同一 `thread_id` 第二次进入时自动加载历史，调用方只传新消息即可 —— 这正好让我们干净地删掉 `rebuild_state`。
- Teammate 的 RAM-only 用 MemorySaver 是默认值，零依赖。
- **重要陷阱（实现中发现）**：同步的 `SqliteSaver` 在 `agent.astream` 调用时会抛 `NotImplementedError: The SqliteSaver does not support async methods` —— 项目 CLI 走 asyncio 必须用 `AsyncSqliteSaver`（底层基于 `aiosqlite`）。Teammate Runner 虽然也 await astream，但因为 MemorySaver 是同步纯内存字典实现，**没有这个问题**。

**Alternatives**：

- 同步 `SqliteSaver` → 与 astream 不兼容（被否，实测）。
- 自定义 SQLite 表 → 工作量大，要自己管 langgraph state 序列化（被否）。
- 用单一 saver 给 Leader 和 Teammate（差异化 thread_id）→ Teammate 焚毁要手动 DELETE，且违反 P1 决策（被否）。

### D2. `thread_id` 语义分两层

| 层 | thread_id | 含义 |
|---|---|---|
| Leader | `session_id`（如 `sess-20260623-001`） | 一次完整对话 |
| Teammate | `teammate_id`（沿用现状 `name@team`） | 一次请求内的 Teammate 实例 |

Teammate 因为每请求都会 `cleanup_spawned_in_turn` 焚毁，所以 thread_id 相同的两次也不会串台（saver 不同）。

### D3. Session 元数据用 JSON，不用 SQLite

`memory/sessions.json` 结构：

```json
{
  "current": "sess-20260623-001",
  "sessions": [
    {
      "id": "sess-20260623-001",
      "title": "查 Q1 销售按地区拆分",
      "created_at": "2026-06-23T14:20:31Z",
      "last_active_at": "2026-06-23T14:35:02Z"
    }
  ]
}
```

**Why JSON**：会话条数量级很小（百级），结构简单；JSON 文件直观、易调试、可手动编辑；原子写靠 `tempfile + os.replace` 即可保证一致性。SQLite 反而是过度设计。

### D4. 标题取用户首条消息前 20 字（中文按字符）

**触发点**：CLI 在把 user_input 追加到 messages 前判断 `session.title` 为空就抽取。抽取规则：

```python
title = user_input.strip()
title = title[:20]  # 中文按 unicode 字符切
if len(user_input.strip()) > 20:
    title += "…"
```

后续永不更新（即使首条很糟糕也保留 —— 用户可用 `/title` 手动改）。

### D5. `/delete <session>` 同步清 checkpoint

`AsyncSqliteSaver` 提供 `adelete_thread(thread_id)` 公开 API（底层执行 `DELETE FROM checkpoints/writes WHERE thread_id=?`）。`LeaderStore.purge` 封装为：

```python
async def purge(self, session_id: str) -> None:
    await self._saver.adelete_thread(session_id)
```

`SessionManager.delete(session_id, leader_store=store)` 内部联动：先 `await leader_store.purge(session_id)` 再从 sessions.json 移除。任何一步失败都抛异常，CLI 报错不退出。

（注：因为 LeaderStore 改成 async，`SessionManager.delete` 也跟着改成 `async def`，CLI 在 `/delete` 命令分支里 `await sm.delete(...)`。）

### D6. ToolMessage 持久化前截断（仅副本）

**阈值**：`_TOOL_MESSAGE_PERSIST_MAX = 4000` 字符（可在 Config 中按环境变量 `TOOL_PERSIST_MAX_CHARS` 覆盖）。

**实现位置**：CLI 在每轮流式结束后，遍历本轮新增的 ToolMessage —— 但**仅修改要写入 checkpointer 的副本**，不动 in-memory 的当 turn 推理上下文。

**关键技巧**：直接在 `agent.astream` 之前/之后改 state 行不通（messages 已被 reducer 合并）。改用 LangGraph 的"post-write hook"思路在我们这层不可行 —— 改成在流式收集到 ToolMessage 时**双份保存**：

```
StreamRenderer:
  collected_messages_runtime: list   # 原文，喂给下一轮（本进程内 SqliteSaver 已经存了完整版？）
  collected_messages_persist: list   # 截断副本
```

可是这么干会让 SqliteSaver 自动落盘的内容（原文）与我们期望的截断副本不一致。**更简洁的替代方案**：在工具调用层（Teammate 的 ToolMessage 还没回到 Leader 时不动；只在 Leader 视角，工具返回作为 ToolMessage 添加进 state 之前 wrap 一层）。但 Leader 调编排工具拿到的 ToolMessage 是 langgraph 内部 add_messages reducer 自动加的，拦不住。

**最终决定**：放弃在 "Leader 推理用原文 / 持久化用截断" 之间做精细切分。改成**统一截断**：超过 4000 字符的 ToolMessage 在工具实现层（`src/orchestration/tools.py` 中各 StructuredTool 的返回值）就截断。理由：

1. 这些工具返回都是结构化 dict，4000 字符够装 ~30 行表格 + 元数据。
2. Teammate 给 Leader 回的实际业务结果是 `task_completed` 消息的 `content` 字段（已经是 Teammate 处理过的总结），不会动辄上万字。
3. 真正大的输出是 NL2SQL 原始结果 —— 那个在 Teammate 内部消费，**不出现在 Leader 视角**，不入 leader.db。
4. 简化实现，避免在 LangGraph 自动持久化和我们的截断逻辑间打架。

`src/persistence/tool_truncate.py` 提供 `truncate_for_persist(content: str, limit: int) -> str` 工具函数，被各工具调用。

### D7. Runner 改造：build 一次 + 累积

```python
class Runner:
    def __init__(self, ...):
        self._agent = None  # lazy

    async def _loop(self):
        # 首次进入循环时构建一次
        self._agent = self._teammate.build_agent_for_prompt()
        ...

    async def _run_one_turn(self, prompt: str) -> str:
        # 不再 build_agent_for_prompt
        state = {"messages": [HumanMessage(content=prompt)]}
        cfg = {"configurable": {"thread_id": self._teammate.context.teammate_id}}
        async for ... in self._agent.astream(state, config=cfg, ...):
            ...
```

`_teammate.build_agent_for_prompt()` 内部仍用 `MemorySaver()`（每个 Runner 一份），但只调用一次，后续 turn 通过 `thread_id` 复用同一 checkpoint。

**SKILL 冻结的含义**：Runner 启动时读 SKILL，运行期间用户改 SKILL 不会被 Teammate 感知（但 Leader 仍能感知，因为 Leader 每 turn 重建）。

### D8. CLI 不再 `rebuild_state`

```python
# 旧：
state = await _run_turn(agent, state, invoke_config)

# 新：
state = {"messages": [HumanMessage(content=user_input)]}
await _run_turn(agent, state, invoke_config)  # 仅消费，不返回
```

LangGraph 看到 `thread_id` 已存在 → 自动从 SqliteSaver 加载历史 → 合并新消息 → 推理 → 写回。CLI 这层只负责渲染流式 token。

### D9. `cleanup_spawned_in_turn` 实现

`TeamManager` 加一个 `_spawned_this_turn: set[teammate_id]`，每次 `spawn_teammate` 加入；CLI 在 `_run_turn` 结束的 `finally` 调 `team_manager.cleanup_spawned_in_turn()`，遍历集合调 `Runner.request_shutdown` + `wait_done`，然后清空集合。**注意**：跨 turn 共享的 Teammate（用户在前一轮 spawn 的）不属于本集合 —— 但鉴于我们决定 Teammate 仅请求内有记忆，**所有** Teammate 都属于本轮新建，所以集合每轮归零。

### D10. 教学 demo 不依赖项目代码

learn/05-memory-persistence/ 下每个 demo 都是独立 Python 脚本，只 import `langgraph` / `langchain`，不 import `src/` 任何模块。让新手可以脱离项目跑通最小例子，再回头读项目代码。

## Risks / Trade-offs

- [SqliteSaver 在并发写入时是 SQLite 级别的锁] → 单 CLI 进程串行用户输入，不存在并发；记录于文档供后续多用户场景时重新评估。
- [`/delete` 物理删除不可逆] → CLI 二次确认提示；不做软删 / 回收站（首版从简）。
- [4000 字符上限可能截掉关键 SQL 输出] → 配置化（`TOOL_PERSIST_MAX_CHARS`），且 Teammate 内部消费的原始结果不受影响；只是 Leader 视角看到的工具回执变短。
- [Teammate SKILL 冻结] → 与 Leader SKILL 热更新不一致；通过 README 和 _SYSTEM_PROMPT 调整明确告知。
- [thread_id 复用导致旧 session 误进入] → SessionManager.current 持久化在 sessions.json；CLI 启动时显式从 current 加载。
- [LangGraph SqliteSaver API 在版本间有差异] → requirements.txt 锁定 `langgraph-checkpoint-sqlite` 版本；测试覆盖核心 API（`get_tuple` / `put`）。
- [sessions.json 与 leader.db 失同步（如手动删了 db 没改 json）] → SessionManager 启动时校验：列表中 session_id 在 db 没 checkpoint 不报错（允许空对话），只在 `/switch` 时若 db 文件本身缺失才报错。

## Migration Plan

1. 加依赖：`pip install langgraph-checkpoint-sqlite -i https://pypi.tuna.tsinghua.edu.cn/simple`，写入 requirements.txt。
2. 新建 `src/persistence/` 包及 `leader_store.py` / `session_manager.py` / `tool_truncate.py`。
3. 改 `src/core/agent.py`：`build_agent(..., checkpointer=None)` 参数化（默认值保持 `MemorySaver()` 以不破坏现有测试）。
4. 改 `src/interface/cli.py`：注入 LeaderStore / SessionManager；删除 `rebuild_state`；新增 session 命令处理。
5. 改 `src/orchestration/runner.py` 和 `team.py`：Runner build 一次、TeamManager 记录本轮新建。
6. 改 `src/orchestration/tools.py`：在 dict 返回处做 `truncate_for_persist`（仅长字段）。
7. 新增 4 个测试文件，全量 `pytest -q` 通过。
8. 输出 learn/05-memory-persistence/ 教学产出。
9. `.gitignore` 加 `memory/`。

无回滚需求：若新机制有缺陷，直接 revert 整个 change，旧的 rebuild_state 路径仍在 git 历史。

## Open Questions

- **SessionManager 是否支持"匿名 session"（没 title 也能用）**？决定：允许；title 留空展示为 `(未命名)`。
- **`/delete` 是否要确认**？建议 CLI 提示 `确定删除会话 'xxx'? [y/N]`，默认 No。落地时实现。
- **多用户后再来一次**？显式 Non-Goal，文档里写清楚 session.json 是单用户模型，未来如果上多用户要重新设计。
