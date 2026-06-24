# 04. Teammate vs Leader —— 双层记忆边界

## 这一节解决的问题

GeneralistAgent 里有两种 Agent，它们的记忆需求完全不同：

| Agent     | 范围           | 介质            | 销毁时机           |
|-----------|----------------|----------------|-------------------|
| Leader    | 永久持续        | SqliteSaver    | 用户主动 `/delete` |
| Teammate  | **本次请求内**  | MemorySaver    | 请求结束自动焚毁   |

为什么这么设计：

- **Leader 长存**：用户期待"明天接着聊"
- **Teammate 短命**：Teammate 是 Leader 临时拉起来打杂的（spawn → 用完即焚）。如果跨请求保留，会出现：
  - 不同用户请求之间 Teammate 状态污染
  - 内存泄漏（Teammate 一直挂着）
  - 调试困难（不知道某轮的 Teammate 是哪轮的产物）

## 双层结构图

```
                      用户请求 turn 边界
              ┌──────────────────────────────────────────────┐
              │  Leader (SqliteSaver) ─── 跨进程持久          │
              │     │                                         │
              │     │ spawn_teammate                          │
              │     ▼                                         │
              │  Teammate A (MemorySaver)  ─── 本 turn 内累积  │
              │  Teammate B (MemorySaver)  ─── 本 turn 内累积  │
              └──────────┬──────────────────────────────────┘
                         │ turn 结束
                         ▼
                  Teammate A / B 被 cleanup_spawned_in_turn 焚毁
                  ─────────────────────────────────────────
                  Leader 状态继续保留在 leader.db
```

## 关键约束

- **Teammate 不写 leader.db**：每个 Teammate 用独立 MemorySaver，绝不持久化
- **Teammate 之间互不可见**：两个 MemorySaver 是不同实例
- **Teammate 同 turn 内多次唤起共享记忆**：Runner 启动时一次性 build agent，thread_id = teammate_id

## demo 在做什么

`demo_two_tier_memory.py`：

1. 起两个 saver：一个 AsyncSqliteSaver（Leader）+ 两个 MemorySaver（两个 Teammate）
2. Leader 第一次说"我叫张三" → SqliteSaver 落盘
3. Teammate A 处理两条消息（"先做 X" → "再做 Y"），第二条能引用第一条 ✓
4. Teammate B 处理一条消息，**完全看不到** Teammate A 的内容 ✓
5. 查看 leader.db 中的 thread_id，**不包含** Teammate 的 id ✓

## 跑

```bash
python learn/05-memory-persistence/04-teammate-vs-leader/demo_two_tier_memory.py
```

预期输出：

```
=== Leader 写一句进 SqliteSaver ===
  Leader.session-1: 我叫张三 → 落盘

=== Teammate A：两次消息共享记忆 ===
  Teammate A turn1: 先做 X
  Teammate A turn2: 再做 Y
  Teammate A 历史长度: 4 ✓ 累积了

=== Teammate B：独立 MemorySaver ===
  Teammate B 历史长度: 2 ✓ 看不到 A 的内容

=== leader.db 中的 thread_id ===
  ['session-1']  ← 仅 Leader，不含 teammate_id
```

## 在项目里的位置

- Leader 持久化：`src/persistence/leader_store.py::LeaderStore`
- Teammate 记忆：`src/orchestration/runner.py::Runner._memory_saver`
- 焚毁机制：下一节
