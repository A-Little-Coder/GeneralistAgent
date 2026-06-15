"""ChatBI Agent 顶层包。

启动时自动加载根目录 `.env`（CLAUDE.md 第 5 条与 design 决策 7）。
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

__version__ = "0.1.0"

# 在任何子包被 import 之前加载 .env，让 Settings 拿到值
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
