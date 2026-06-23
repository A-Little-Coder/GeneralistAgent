"""
GeneralistAgent 入口 — 启动 CLI 异步交互式智能体。

使用方式：
    python src/main.py

初始化流程：
  1. 加载配置（.env）
  2. 初始化 LLM 模型
  3. 初始化 SkillCenter（远程 SQLite + 本地技能目录同步）
  4. 进入异步交互主循环（asyncio.run）
"""

import asyncio

from src.interface.cli import repl
from src.core.config import load_config
from src.core.model import init_model
from src.skills.center import SkillCenter


def main() -> None:
    config = load_config()
    model = init_model(config)
    skill_center = SkillCenter(remote_db_dir=config.remote_db_dir, local_skills_dir=config.skills_dir)
    asyncio.run(repl(model=model, skill_center=skill_center, config=config))


if __name__ == "__main__":
    main()