"""ChatBI 配置加载模块。

基于 `pydantic-settings` 实现配置项的统一加载，覆盖优先级：

    环境变量 > 项目根目录 `.env` 文件 > 字段默认值

字段名按 `pydantic-settings` 默认大小写不敏感的方式自动映射环境变量，
例如 `qwen_api_key` 字段会从 `QWEN_API_KEY` 环境变量读取。

对外暴露：
    - `Settings`：配置数据类，承载全部配置字段；
    - `get_settings()`：基于 `functools.lru_cache` 的单例工厂。
      单元测试中如需重置缓存，可调用 `get_settings.cache_clear()`。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ChatBI 全局运行时配置。

    字段说明见各 Field 的 `description`。新增字段时请同步更新 `.env.example`
    与文档；若字段含敏感信息，请勿写入默认值。
    """

    # === LangSmith 可观测性 ===
    langsmith_api_key: str = Field(
        default="",
        description="LangSmith API Key，用于 Tracer 上报；空字符串表示禁用上报。",
    )
    langchain_project: str = Field(
        default="chatbi-dev",
        description="LangSmith 项目名（同一环境的 trace 会聚合到该项目下）。",
    )

    # === 运行环境标识 ===
    chatbi_env: str = Field(
        default="dev",
        description="部署环境标识，取值范围：dev / staging / prod。",
    )

    # === LLM 接入（Qwen / DashScope，OpenAI 兼容协议）===
    qwen_api_key: str = Field(
        default="",
        description="Qwen / DashScope API Key（OpenAI 兼容接口）。",
    )
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="Qwen / DashScope OpenAI 兼容接口的 Base URL。",
    )
    qwen_model: str = Field(
        default="qwen-plus",
        description="默认使用的 Qwen 模型名。",
    )

    # === 日志 ===
    log_level: str = Field(
        default="INFO",
        description="root logger 日志级别，常见取值：DEBUG / INFO / WARNING / ERROR。",
    )

    # pydantic-settings 配置：
    #   - env_file：项目根目录 `.env`；
    #   - case_sensitive=False：允许大小写自动匹配；
    #   - extra="ignore"：忽略 .env 中未在本类声明的多余键（如 BGE_M3_MODEL_PATH），避免启动失败。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取全局 `Settings` 单例。

    使用 `functools.lru_cache` 保证进程内仅实例化一次，避免重复读取 `.env`。
    单元测试若需要修改环境变量后重新加载，请显式调用：

        >>> get_settings.cache_clear()
        >>> get_settings()  # 触发一次新的实例化
    """

    return Settings()
