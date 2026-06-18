"""
配置管理模块 — 从 .env 加载并校验配置项。
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """应用配置，从 .env 加载。"""

    # LLM 配置
    api_key: str
    base_url: str
    model_name: str
    model_provider: str = "openai"

    # LangSmith 链路追踪（可选）
    langchain_tracing: bool = False
    langsmith_api_key: str = ""
    langchain_project: str = "GeneralistAgent"

    # 本地嵌入模型路径（可选）
    bge_m3_model_path: str = ""

    # 项目路径
    skills_dir: str = field(default="")       # 本地 skills/ 目录
    remote_db_dir: str = field(default="")    # 远程数据库目录

    @property
    def model_spec(self) -> str:
        """返回 init_chat_model 可识别的 provider:model 格式。"""
        return f"openai:{self.model_name}"


def load_config() -> Config:
    """从项目根目录 .env 加载配置，缺失必填项时报错退出。"""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    if not env_path.exists():
        print("❌ 未找到 .env 文件")
        print(f"   请将 {env_path.parent / '.env.example'} 复制为 .env 并填入 API Key")
        sys.exit(1)

    load_dotenv(env_path)

    api_key = os.getenv("QWEN_API_KEY", "")
    if not api_key:
        print("❌ 环境变量 QWEN_API_KEY 未设置")
        print("   请在 .env 中填入你的 API Key")
        sys.exit(1)

    root = env_path.parent

    return Config(
        api_key=api_key,
        base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model_name=os.getenv("QWEN_MODEL", "qwen-plus"),
        model_provider=os.getenv("MODEL_PROVIDER", "openai"),

        langchain_tracing=os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
        langsmith_api_key=os.getenv("LANGSMITH_API_KEY", ""),
        langchain_project=os.getenv("LANGCHAIN_PROJECT", "GeneralistAgent"),

        bge_m3_model_path=os.getenv("BGE_M3_MODEL_PATH", ""),

        skills_dir=str(root / "skills"),
        remote_db_dir=str(root / "remote" / "skills"),
    )