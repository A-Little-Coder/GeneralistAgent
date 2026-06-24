"""
持久化层 —— Leader 跨进程对话历史 + Session 元数据。

模块边界：
  - leader_store     :  SqliteSaver 封装；memory/leader.db
  - session_manager  :  Session CRUD 元数据；memory/sessions.json
  - tool_truncate    :  工具返回入库前的截断助手

Teammate 不在本层；其记忆完全 RAM 化（MemorySaver in Runner）。
"""

from src.persistence.leader_store import LeaderStore
from src.persistence.session_manager import Session, SessionManager
from src.persistence.tool_truncate import truncate_for_persist

__all__ = [
    "LeaderStore",
    "Session",
    "SessionManager",
    "truncate_for_persist",
]
