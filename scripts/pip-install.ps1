# 使用清华镜像源安装 ChatBI 依赖（CLAUDE.md 第 5 条强制要求）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/pip-install.ps1
$ErrorActionPreference = "Stop"

$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple"
$RootDir = Split-Path -Parent $PSScriptRoot

Write-Host "→ 使用清华镜像源安装：$Mirror"
pip install -r "$RootDir\requirements.txt" -i $Mirror @args
Write-Host "✓ 依赖安装完成"
