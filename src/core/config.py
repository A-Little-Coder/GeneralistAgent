"""
配置管理模块 — 从 .env 加载并校验配置项。
"""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src.orchestration.proxy_tools import ProxyServiceConfig


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
    teams_root: str = field(default="")       # 团队共享 TaskList 根目录（项目内，不跨项目共用）

    # 外部代理服务配置（从 PROXY_<NAME>_* 环境变量解析）
    proxy_services: list = field(default_factory=list)  # list[ProxyServiceConfig]

    @property
    def model_spec(self) -> str:
        """返回 init_chat_model 可识别的 provider:model 格式。"""
        return f"openai:{self.model_name}"

    def get_proxy_service(self, name: str) -> Optional[ProxyServiceConfig]:
        """按服务名查找代理服务配置，找不到返回 None。"""
        for svc in self.proxy_services:
            if svc.name == name:
                return svc
        return None


# .env 中代理服务变量的正则：PROXY_<NAME>_<FIELD>
_PROXY_ENV_RE = re.compile(r"^PROXY_([A-Z0-9]+)_([A-Z_]+)$")


def _parse_proxy_services_from_env() -> list[ProxyServiceConfig]:
    """从 os.environ 解析所有 `PROXY_<NAME>_*` 配置项，聚合为 ProxyServiceConfig 列表。

    支持的字段（不区分大小写）：
      ACCESS_KIND / BASE_URL / AUTH_HEADER / TIMEOUT / MCP_COMMAND / SKILL_NAME

    必须 ACCESS_KIND 非空才会被注册；其他字段缺省走 dataclass 默认值。
    """
    buckets: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        m = _PROXY_ENV_RE.match(key)
        if not m:
            continue
        name = m.group(1).lower()
        field_name = m.group(2).lower()
        buckets.setdefault(name, {})[field_name] = value

    services: list[ProxyServiceConfig] = []
    for name, fields in buckets.items():
        access_kind = fields.get("access_kind", "").strip().lower()
        if not access_kind:
            continue  # 没声明访问方式 → 跳过

        timeout_str = fields.get("timeout", "30").strip()
        try:
            timeout = int(timeout_str)
        except ValueError:
            timeout = 30

        services.append(ProxyServiceConfig(
            name=name,
            access_kind=access_kind,
            base_url=fields.get("base_url", "").strip(),
            auth_header=fields.get("auth_header", "").strip(),
            timeout=timeout,
            mcp_command=fields.get("mcp_command", "").strip(),
            skill_name=fields.get("skill_name", "").strip(),
        ))
    return services


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
        teams_root=str(root / "teams"),

        proxy_services=_parse_proxy_services_from_env(),
    )
