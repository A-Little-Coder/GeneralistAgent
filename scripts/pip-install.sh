#!/usr/bin/env bash
# 使用清华镜像源安装 ChatBI 依赖（CLAUDE.md 第 5 条强制要求）
# 用法：bash scripts/pip-install.sh [extra pip args]
set -euo pipefail

MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ 使用清华镜像源安装：$MIRROR"
pip install -r "$ROOT_DIR/requirements.txt" -i "$MIRROR" "$@"
echo "✓ 依赖安装完成"
