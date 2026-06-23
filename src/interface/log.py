"""
统一日志辅助模块 —— 多层来源带前缀 + 彩色输出 + 终端能力自动降级。

输出格式约定：
  [Leader]   ...        cyan
  [Teammate name] ...   各 Teammate 分配的 color
  [NL2SQL]   ...        magenta
  [Orchestrator] ...    yellow
  [Mailbox]  ...        blue
  [TaskList] ...        grey
  [Proxy]    ...        magenta（HTTP/MCP 通用代理工具）

事件视觉字符（统一约定）：
  🛠   工具调用
  📥   工具返回
  🡒    请求出
  🡐    响应入
  ✓    成功
  ✗    错误
  ⏱    超时

设计要点：
  - 不依赖第三方库（colorama / loguru）；用纯 ANSI 序列
  - Windows 终端默认 UTF-8 已在 cli.py 模块顶部强制开启
  - 自动检测 ANSI 支持：sys.stdout.isatty() + 环境变量 NO_COLOR
  - 所有函数都是 thread-safe 的 print()，REPL 单进程足够用
"""

from __future__ import annotations

import os
import sys
from typing import Any


# ── ANSI 颜色码 ───────────────────────────────────────────────────────


_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
    # 各 Teammate 分配色池（按 hash 选）
    "_teammate_palette": [
        "\033[92m",   # bright green
        "\033[93m",   # bright yellow
        "\033[94m",   # bright blue
        "\033[95m",   # bright magenta
        "\033[96m",   # bright cyan
        "\033[91m",   # bright red
    ],
}


def _ansi_enabled() -> bool:
    """是否启用 ANSI 输出。NO_COLOR 环境变量可强制关闭（标准约定）。"""
    if os.environ.get("NO_COLOR"):
        return False
    # 非 TTY（管道 / 文件重定向）默认关闭，保证日志干净
    stream = sys.stdout
    return hasattr(stream, "isatty") and stream.isatty()


# 模块加载时一次性决定，避免每次调用都判断
_ENABLED = _ansi_enabled()


def _wrap(text: str, color: str) -> str:
    """套上颜色码（若启用），关闭时直接返回 text。"""
    if not _ENABLED:
        return text
    code = _COLORS.get(color, "")
    if not code:
        return text
    return f"{code}{text}{_COLORS['reset']}"


# ── 通用打印 ──────────────────────────────────────────────────────────


def _log(prefix: str, prefix_color: str, message: str) -> None:
    """通用打印：[Prefix] message，prefix 部分上色。"""
    colored_prefix = _wrap(prefix, prefix_color)
    print(f"{colored_prefix} {message}", flush=True)


# ── 各来源的便捷函数 ─────────────────────────────────────────────────


def leader_log(message: str) -> None:
    """Leader 自身输出（流式 token / 工具调用等）。"""
    _log("[Leader]", "cyan", message)


def teammate_log(name: str, message: str) -> None:
    """单个 Teammate 的痕迹（color 按 name 散列分配）。"""
    palette = _COLORS["_teammate_palette"]
    color_code = palette[hash(name) % len(palette)]
    if _ENABLED:
        prefix = f"{color_code}[Teammate {name}]{_COLORS['reset']}"
    else:
        prefix = f"[Teammate {name}]"
    print(f"{prefix} {message}", flush=True)


def nl2sql_log(message: str) -> None:
    """NL2SQL 代理工具的请求 / SSE 事件 / 结果日志。"""
    _log("[NL2SQL]", "magenta", message)


def proxy_log(message: str) -> None:
    """通用 HTTP / MCP 代理工具日志（非 NL2SQL）。"""
    _log("[Proxy]", "magenta", message)


def indent_log(message: str) -> None:
    """缩进日志 —— 用在 Leader 的工具内部执行细节。"""
    _log("[Leader]", "cyan", f"  {message}")


# ── 通用快捷格式化 ───────────────────────────────────────────────────


def fmt_kv(d: dict, max_value_len: int = 80) -> str:
    """把 dict 紧凑序列化为 k=v 形式，长 value 截断。便于一行日志携带参数。"""
    parts = []
    for k, v in d.items():
        s = str(v)
        if len(s) > max_value_len:
            s = s[:max_value_len] + "…"
        parts.append(f"{k}={s}")
    return " ".join(parts)


def truncate(s: Any, n: int = 200) -> str:
    """安全截断 —— 配合日志预览。"""
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"
