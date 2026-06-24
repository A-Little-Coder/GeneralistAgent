## MODIFIED Requirements

### Requirement: 资源清理
系统 SHALL 在两个时机清理 Teammate 资源：(1) 每轮用户请求结束时焚毁本轮新建的 Teammate（与 `teammate-runtime-memory` 能力配合）；(2) 进程退出时清理仍残留的活跃团队与 Teammate，避免 asyncio Task 与文件残留。

#### Scenario: 每轮请求结束焚毁本轮 Teammate
- **WHEN** Leader 完成一轮用户请求的回复
- **THEN** 系统 SHALL 调用 `team_manager.cleanup_spawned_in_turn()`，对本轮 `spawn_teammate` 创建的所有 Teammate 发起 shutdown 并等待 Runner 退出

#### Scenario: 进程退出清理
- **WHEN** REPL 主循环退出（用户输入 exit 或进程终止）
- **THEN** 系统 SHALL 向所有活跃 Teammate 发送 shutdown 并清理其 asyncio Task 与 Task List 文件

#### Scenario: 活跃团队可查
- **WHEN** Leader 调用 `team_list`
- **THEN** 系统 SHALL 返回当前所有活跃团队及其成员状态，便于排查资源泄漏
