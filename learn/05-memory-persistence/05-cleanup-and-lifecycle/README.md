# 05. Cleanup & Lifecycle —— Teammate 创建 / 唤起 / 焚毁

## 这一节解决的问题

Teammate 在请求结束时必须被**彻底销毁** —— 否则：

- `asyncio.Task` 永远挂着 → 内存泄漏
- 下一轮的同名 Teammate 会"复活"上一轮的记忆 → 串台
- 调试时无法判断"现在哪些 Teammate 在跑"

## 生命周期

```
   ┌────────────────────────────────────────────────────────────────┐
   │ 一轮用户请求                                                    │
   │                                                                │
   │  Leader 调 spawn_teammate(name="A")                             │
   │     │                                                          │
   │     ├──► TeamManager._spawned_this_turn += (team, "A")         │
   │     │                                                          │
   │     └──► Team.add_teammate(A) → Runner.start() → asyncio.Task  │
   │                                  │                             │
   │                                  ├── idle 循环                  │
   │                                  ├── 收消息 → _run_one_turn     │
   │                                  └── ...                       │
   │                                                                │
   │  Leader 多次 send_message / assign_task                         │
   │     ├── Runner 处理（共享同一 MemorySaver）                      │
   │     └── ...                                                    │
   │                                                                │
   │  ── 用户请求结束 ──                                              │
   │                                                                │
   │  CLI finally: team_manager.cleanup_spawned_in_turn()            │
   │     │                                                          │
   │     ├── 遍历 _spawned_this_turn                                 │
   │     ├── runner.request_shutdown()                              │
   │     ├── runner.wait_done()                                     │
   │     ├── team.members.pop("A")                                  │
   │     └── _spawned_this_turn.clear()                             │
   │                                                                │
   │  GC：MemorySaver 引用归零 → 回收                                 │
   └────────────────────────────────────────────────────────────────┘
```

## 关键 API

- `TeamManager.spawn_teammate(team, t)` — 标记入本轮 set
- `TeamManager.cleanup_spawned_in_turn()` — 焚毁集合内全部，返回数量
- `TeamManager.spawned_this_turn` — 只读快照（调试 / 测试用）
- `Runner.request_shutdown()` + `Runner.wait_done()` — 单个 Runner 收尾

## demo 在做什么

`demo_cleanup.py`（不依赖真实 LLM）：

1. 起一个最小的"Teammate 模型"：实际上是 `asyncio.Task` 在循环 `await sleep`，模拟 Runner 永不退出
2. 用一个"焚毁器"模拟 `cleanup_spawned_in_turn`：发 cancel + await done
3. 演示：创建 3 个 → 累积一会儿 → 焚毁 → 再创建一个

主要看终端打印的"活跃 Teammate 数"曲线。

## 跑

```bash
python learn/05-memory-persistence/05-cleanup-and-lifecycle/demo_cleanup.py
```

预期输出：

```
=== 起 3 个 Teammate ===
  活跃: 3
=== 第一轮工作中... ===
  活跃: 3   (持续干活)
=== cleanup_spawned_in_turn ===
  焚毁数: 3
  活跃: 0   ✓ 全焚干净
=== 下一轮：起一个新的 ===
  活跃: 1   ← 全新实例
=== 退出前清理 ===
  活跃: 0
```

## 在项目里的位置

- `src/orchestration/team.py::TeamManager.cleanup_spawned_in_turn` —— 真实焚毁逻辑
- `src/interface/cli.py::_repl_loop` —— 每轮 `finally` 调用
- `tests/test_cleanup_turn.py` —— 完整覆盖
