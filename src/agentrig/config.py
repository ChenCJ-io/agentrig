"""AgentRig 配置（基于 pydantic-settings）。

配置从 `AGENTRIG_*` 环境变量加载（嵌套用 `__` 分隔，如
`AGENTRIG_QWEN__API_KEY`）。TOML 文件支持留到后续 PR。
"""
from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    """HTTP 服务绑定配置。"""

    host: str = "127.0.0.1"
    port: int = 8000


class AgentConfig(BaseSettings):
    """被测 agent 的连接配置。"""

    server_url: str = ""
    user_id: str = "agentrig"
    request_timeout: float = 60.0


class DatabaseConfig(BaseSettings):
    """持久化配置（v0.1 可选，无 DB 时降级内存）。"""

    url: str = ""
    schema_name: str = "agentrig"


class QwenConfig(BaseSettings):
    """LLM provider 配置（默认 Qwen；后续通过 LLMProvider 抽象可插拔）。"""

    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    model: str = ""


class Settings(BaseSettings):
    """顶层配置，从环境变量加载。

    嵌套字段用 `__` 分隔，如 `AGENTRIG_SERVER__PORT=9000`。
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTRIG_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: str = "dev"
    server: ServerConfig = ServerConfig()
    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    qwen: QwenConfig = QwenConfig()


def get_settings() -> Settings:
    """加载并返回配置（暂未缓存，需要时再加 lru_cache）。"""
    return Settings()
