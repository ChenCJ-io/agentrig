"""AgentRig 配置（基于 pydantic-settings）。

配置来源（优先级高 → 低）：构造参数 > 环境变量 > TOML 文件 > 默认值。
- 环境变量：`AGENTRIG_*`，嵌套用 `__` 分隔（如 `AGENTRIG_LLM__API_KEY`）
- TOML：默认读 `agentrig.toml` 顶层字段（文件不存在则忽略）

agentrig.toml 示例::

    environment = "prod"

    [server]
    port = 9000

    [llm]
    api_key = "sk-..."
    model = "gpt-x"
"""
from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


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
    """持久化配置（无 url 时降级内存）。"""

    url: str = ""
    schema_name: str = "agentrig"


class LLMConfig(BaseSettings):
    """LLM provider 配置（OpenAI 兼容；通过 LLMProvider 抽象可插拔）。"""

    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    model: str = ""


class ProxyConfig(BaseSettings):
    """Proxy 后端配置：namespace -> 后端 MCP server URL。

    从环境变量加载 JSON，如::

        AGENTRIG_PROXY__BACKENDS='{"echo":"http://localhost:9001/mcp"}'
    """

    backends: dict[str, str] = {}


class Settings(BaseSettings):
    """顶层配置：构造参数 > 环境变量 > TOML > 默认值。

    环境变量 `AGENTRIG_*`，嵌套 `__` 分隔。TOML 默认读 `agentrig.toml` 顶层。
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENTRIG_",
        env_nested_delimiter="__",
        extra="ignore",
        toml_file="agentrig.toml",
    )

    environment: str = "dev"
    server: ServerConfig = ServerConfig()
    agent: AgentConfig = AgentConfig()
    database: DatabaseConfig = DatabaseConfig()
    llm: LLMConfig = LLMConfig()
    proxy: ProxyConfig = ProxyConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 优先级：构造参数 > 环境变量 > TOML > dotenv > secret。
        # TomlConfigSettingsSource 对不存在的文件静默忽略（配置文件可选）。
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


def get_settings() -> Settings:
    """加载并返回配置（暂未缓存，需要时再加 lru_cache）。"""
    return Settings()
