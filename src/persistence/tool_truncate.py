"""
truncate_for_persist —— 工具返回写入 Leader 持久化层前的截断助手。

设计要点：
  - 阈值由环境变量 TOOL_PERSIST_MAX_CHARS 覆盖，默认 4000 字符（中文按字符计）
  - 仅对超过阈值的字符串截断并追加注脚 …[已截断，原文 N 字符]
  - 非 str 类型原样返回，调用方负责自行序列化
  - 阈值 <= 0 视为不截断（关闭功能）

为何 4000 字符：
  - NL2SQL 典型 SQL+结果 < 2000 字符
  - Markdown 表格 20 行 × 5 列 ≈ 1500 字符
  - 留一倍余量；后续如发现常被截可调高
"""

from __future__ import annotations

import os
from typing import Optional


_DEFAULT_LIMIT = 4000
_ENV_KEY = "TOOL_PERSIST_MAX_CHARS"
_TRUNCATE_NOTE = "…[已截断，原文 {n} 字符]"


def _resolve_limit(limit: Optional[int]) -> int:
    """优先级：函数参数 > 环境变量 > 默认 4000。"""
    if limit is not None:
        return limit
    raw = os.environ.get(_ENV_KEY, "").strip()
    if not raw:
        return _DEFAULT_LIMIT
    try:
        return int(raw)
    except ValueError:
        # 环境变量非整数 → 回退默认，不抛
        return _DEFAULT_LIMIT


def truncate_for_persist(content: str, limit: Optional[int] = None) -> str:
    """对长字符串做"前 N 字符 + 截断注脚"处理。

    Args:
        content: 待截断文本；非 str 直接 cast 后处理。
        limit: 字符上限；None 时读环境变量 TOOL_PERSIST_MAX_CHARS，再 fallback 默认 4000。
               传入 0 或负数 → 不截断（关闭）。

    Returns:
        截断后的字符串（短于阈值时原样返回）。
    """
    if content is None:
        return ""

    text = content if isinstance(content, str) else str(content)
    effective = _resolve_limit(limit)
    if effective <= 0:
        return text

    n = len(text)
    if n <= effective:
        return text

    return text[:effective] + _TRUNCATE_NOTE.format(n=n)


def truncate_dict_fields(
    data: dict,
    fields: tuple[str, ...] = ("content", "reason", "result"),
    limit: Optional[int] = None,
) -> dict:
    """对 dict 中指定字段做截断（in-place），其他字段不动。

    便于在工具返回值上做"只截这几个长字段"的批量处理。
    """
    for key in fields:
        if key in data and isinstance(data[key], str):
            data[key] = truncate_for_persist(data[key], limit=limit)
    return data
