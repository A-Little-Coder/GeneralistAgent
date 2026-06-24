"""
user_migration —— 旧数据一次性迁移到 user_id 维度。

两条迁移路径：

1. `migrate_legacy_thread_ids(conn)`：
   - 把 leader.db 中所有 thread_id 不含 ':' 的行
     改为 'default:<原值>'，事务保护、幂等
2. `migrate_legacy_sessions_dict(data)`：
   - 旧格式 {"current": ..., "sessions": [...]} → 新格式
     {"users": {"default": {"current": ..., "sessions": [...]}}}
   - 已是新格式则原样返回

两个函数都是**幂等**的：再次执行不会破坏新格式。

约束（与 design.md D4 / D5 一致）：
  - thread_id 唯一分隔符是冒号 `:`
  - user_id 不含冒号，session_id 由 `session-N` 生成天然不含冒号
  - 失败回滚：SQL 用 BEGIN/COMMIT；JSON 由调用方原子写
"""

from __future__ import annotations

from typing import Any, Optional

import aiosqlite


# 旧数据归到这个默认 user 下
_DEFAULT_USER_ID = "default"


async def migrate_legacy_thread_ids(
    conn: aiosqlite.Connection,
    default_user_id: str = _DEFAULT_USER_ID,
) -> int:
    """把 checkpoints + writes 中无冒号的 thread_id 改名为 `<default_user>:<原值>`。

    用 SQL 事务保护：失败回滚，磁盘状态不变。

    Returns:
        受影响的总行数（checkpoints + writes 之和）。0 表示已迁过或无旧数据。
    """
    affected = 0
    try:
        # 显式开事务（aiosqlite 默认 deferred，写时升级到 immediate）
        await conn.execute("BEGIN")
        for table in ("checkpoints", "writes"):
            cur = await conn.execute(
                f"UPDATE {table} "
                f"SET thread_id = ? || thread_id "
                f"WHERE thread_id NOT LIKE '%:%'",
                (f"{default_user_id}:",),
            )
            affected += cur.rowcount or 0
            await cur.close()
        await conn.commit()
    except Exception:
        # 任何失败回滚；让上层决定是否吞掉
        try:
            await conn.rollback()
        except Exception:
            pass
        raise
    return affected


def migrate_legacy_sessions_dict(
    data: Any,
    default_user_id: str = _DEFAULT_USER_ID,
) -> tuple[dict, bool]:
    """把旧格式 sessions.json dict 转为新格式（users 分组）。

    新格式：
        {
          "users": {
            "<user_id>": {
              "current": "<session_id>"|null,
              "sessions": [...]
            }
          }
        }

    旧格式（无 users 字段）：
        {
          "current": "<session_id>"|null,
          "sessions": [...]
        }

    Args:
        data: 从 json.load 得到的对象（可能是空 dict / 损坏内容，本函数会兜底返回空新格式）
        default_user_id: 旧数据归到的 user_id

    Returns:
        (new_data, migrated)
          - new_data：始终是新格式 dict
          - migrated：True 表示发生了迁移，调用方应立即落盘
    """
    if not isinstance(data, dict):
        return ({"users": {}}, False)

    # 已是新格式（含 users 字段就认为是新格式，即便 users 空）
    if "users" in data and isinstance(data["users"], dict):
        return (data, False)

    # 旧格式或残缺：包到 default 桶下
    old_sessions = data.get("sessions", []) if isinstance(data.get("sessions"), list) else []
    old_current = data.get("current") if isinstance(data.get("current"), (str, type(None))) else None

    new_data = {
        "users": {
            default_user_id: {
                "current": old_current,
                "sessions": old_sessions,
            }
        }
    }
    return (new_data, True)


def empty_users_dict() -> dict:
    """空的新格式 sessions.json 内容。"""
    return {"users": {}}


__all__ = [
    "migrate_legacy_thread_ids",
    "migrate_legacy_sessions_dict",
    "empty_users_dict",
]
