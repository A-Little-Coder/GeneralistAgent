"""
多 Agent 协作基础设施 — 参考 Claude Code Agent Teams 机制。

模块组成：
  - context.py   : TeammateContext（同进程身份隔离，基于 contextvars）
  - task_list.py : 共享 Task List（JSON 文件持久化）
  - mailbox.py   : Mailbox（asyncio.Queue 消息通道）
  - teammate.py  : Teammate 身份 + 独立 LLM 实例
  - runner.py    : Runner（asyncio Task idle 循环，自动领任务收消息）
  - team.py      : Team 容器生命周期
  - tools.py     : 编排工具（暴露给 Leader 调用）
"""
