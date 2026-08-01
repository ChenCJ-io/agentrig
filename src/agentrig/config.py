"""AgentRig 配置（基于 pydantic-settings）。

配置来源（优先级高 → 低）：构造参数 > 环境变量 > TOML 文件 > 默认值。
- 环境变量：`AGENTRIG_*`，嵌套用 `__` 分隔
- TOML：默认读 `agentrig.toml` 顶层字段（文件不存在则忽略）

agentrig.toml 示例::

    environment = "prod"

    [server]
    port = 9000

    [execution]
    default_concurrency = 4
"""
from __future__ import annotations

from pydantic import Field, field_validator
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
    # 非空时 /api /mcp /proxy 需 Authorization: Bearer <token>（公网暴露务必设置）
    api_token_ref: str | None = None
    log_level: str = "INFO"

    @field_validator("api_token_ref")
    @classmethod
    def token_is_an_environment_reference(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("env:") or value == "env:"):
            raise ValueError("api_token_ref must use env:VARIABLE_NAME")
        return value


class DatabaseConfig(BaseSettings):
    """V1 数据库配置。

    ``url`` 接受 SQLAlchemy asyncio URL。留空时，应用使用工作目录下的
    ``.agentrig/agentrig.db``；测试可以显式传 ``sqlite+aiosqlite:///:memory:``。
    """

    url: str = ""
class ExecutionConfig(BaseSettings):
    """进程内 Scheduler 与外部组件的部署上限。"""

    default_concurrency: int = 4
    max_concurrency: int = 20
    default_case_timeout_seconds: float = 300.0
    default_component_timeout_seconds: float = 60.0
    real_tool_allowlist: list[str] = []
    python_driver_allowlist: list[str] = []
    subprocess_allowlist: list[str] = []


class EvidenceConfig(BaseSettings):
    """运行证据落库前的统一脱敏配置。"""

    sensitive_keys: list[str] = [
        "authorization",
        "cookie",
        "api_key",
        "token",
        "secret",
    ]
    sensitive_paths: list[str] = []
    max_event_payload_bytes: int = 1_000_000


class ProxyConfig(BaseSettings):
    """Proxy 后端配置：namespace -> 后端 MCP server URL。

    从环境变量加载 JSON，如::

        AGENTRIG_PROXY__BACKENDS='{"echo":"http://localhost:9001/mcp"}'
    """

    backends: dict[str, str] = {}
    # 被测 Agent 可访问的 Proxy 地址。留空时按 server.host/server.port 推导；
    # 容器、远端 Target 或反向代理部署应显式配置。
    public_url: str = ""


class AssistantConfig(BaseSettings):
    """V2 助手事件流与确认策略的部署上限。"""

    sse_poll_interval_seconds: float = 0.5
    sse_heartbeat_seconds: float = 15.0
    max_message_chars: int = 100_000


class MatrixConfig(BaseSettings):
    """AgentRig Bridge 使用的 Matrix Client-Server API 配置。"""

    homeserver_url: str = ""
    access_token_ref: str | None = None
    bridge_user_id: str = ""
    manager_user_id: str = ""
    curator_user_id: str = ""
    judge_user_id: str = ""
    default_worker_room_id: str = ""
    request_timeout_seconds: float = 15.0

    @field_validator("access_token_ref")
    @classmethod
    def token_is_an_environment_reference(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("env:") or value == "env:"):
            raise ValueError("access_token_ref must use env:VARIABLE_NAME")
        return value


class AgentTeamsConfig(BaseSettings):
    """外部 AgentTeams/Matrix 集成开关；默认关闭以保持 V1 自包含。"""

    enabled: bool = False
    health_url: str = ""
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)
    manager_mcp_token_ref: str | None = None
    curator_mcp_token_ref: str | None = None
    judge_mcp_token_ref: str | None = None

    @field_validator(
        "manager_mcp_token_ref",
        "curator_mcp_token_ref",
        "judge_mcp_token_ref",
    )
    @classmethod
    def tokens_are_environment_references(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("env:") or value == "env:"):
            raise ValueError("role MCP token references must use env:VARIABLE_NAME")
        return value


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
    database: DatabaseConfig = DatabaseConfig()
    execution: ExecutionConfig = ExecutionConfig()
    evidence: EvidenceConfig = EvidenceConfig()
    proxy: ProxyConfig = ProxyConfig()
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    agentteams: AgentTeamsConfig = Field(default_factory=AgentTeamsConfig)

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
