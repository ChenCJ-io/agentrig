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

import os

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class ServerConfig(BaseSettings):
    """HTTP 服务绑定配置。"""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65_535)
    # 非空时 /api /mcp /proxy 需 Authorization: Bearer <token>（公网暴露务必设置）
    api_token_ref: str | None = None
    log_level: str = "INFO"
    # 默认忽略调用方自报身份。仅在可信反向代理会剥离并重写该 Header 时配置。
    trusted_principal_header: str | None = None

    @field_validator("api_token_ref")
    @classmethod
    def token_is_an_environment_reference(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("env:") or value == "env:"):
            raise ValueError("api_token_ref must use env:VARIABLE_NAME")
        return value

    @field_validator("trusted_principal_header")
    @classmethod
    def principal_header_is_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized or any(
            not (character.isalnum() or character == "-") for character in normalized
        ):
            raise ValueError("trusted_principal_header must be a valid HTTP header name")
        return normalized


class DatabaseConfig(BaseSettings):
    """V1 数据库配置。

    ``url`` 接受 SQLAlchemy asyncio URL。留空时，应用使用工作目录下的
    ``.agentrig/agentrig.db``；测试可以显式传 ``sqlite+aiosqlite:///:memory:``。
    """

    url: str = ""


class ExecutionConfig(BaseSettings):
    """进程内 Scheduler 与外部组件的部署上限。"""

    default_concurrency: int = Field(default=4, ge=1)
    max_concurrency: int = Field(default=20, ge=1)
    default_case_timeout_seconds: float = Field(default=300.0, gt=0)
    default_component_timeout_seconds: float = Field(default=60.0, gt=0)
    max_repeat_count: int = Field(default=20, ge=1)
    max_cases_per_run: int = Field(default=200, ge=1)
    max_planned_case_runs: int = Field(default=1_000, ge=1)
    real_tool_allowlist: list[str] = Field(default_factory=list)
    python_driver_allowlist: list[str] = Field(default_factory=list)
    subprocess_allowlist: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def concurrency_defaults_fit_deployment_limit(self) -> ExecutionConfig:
        if self.default_concurrency > self.max_concurrency:
            raise ValueError("default_concurrency cannot exceed max_concurrency")
        return self


class EvidenceConfig(BaseSettings):
    """运行证据落库前的统一脱敏配置。"""

    sensitive_keys: list[str] = [
        "authorization",
        "cookie",
        "api_key",
        "token",
        "secret",
    ]
    sensitive_paths: list[str] = Field(default_factory=list)
    max_event_payload_bytes: int = Field(default=1_000_000, ge=1_024)


class ProxyConfig(BaseSettings):
    """Proxy 后端配置：namespace -> 后端 MCP server URL。

    从环境变量加载 JSON，如::

        AGENTRIG_PROXY__BACKENDS='{"echo":"http://localhost:9001/mcp"}'
    """

    backends: dict[str, str] = Field(default_factory=dict)
    # 被测 Agent 可访问的 Proxy 地址。留空时按 server.host/server.port 推导；
    # 容器、远端 Target 或反向代理部署应显式配置。
    public_url: str = ""


class TargetNetworkConfig(BaseSettings):
    """Target HTTP 出站边界；显式 allowlist 可放行受信私网主机。"""

    allow_private_networks: bool = False
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )

    @field_validator("allowed_hosts")
    @classmethod
    def allowed_host_patterns_are_valid(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            host = item.strip().lower().rstrip(".")
            if not host or "://" in host or "/" in host:
                raise ValueError("allowed_hosts entries must be hostnames without scheme or path")
            if "*" in host and (not host.startswith("*.") or host.count("*") != 1):
                raise ValueError("allowed_hosts only supports a leading '*.' wildcard")
            normalized.append(host)
        return list(dict.fromkeys(normalized))


class ReportingConfig(BaseSettings):
    """服务端报告与导出的内存和响应规模边界。"""

    max_report_case_runs: int = Field(default=10_000, ge=1, le=100_000)
    max_export_records: int = Field(default=10_000, ge=1, le=100_000)


class AssistantConfig(BaseSettings):
    """V2 助手事件流与确认策略的部署上限。"""

    sse_poll_interval_seconds: float = Field(default=0.5, gt=0)
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    max_message_chars: int = Field(default=100_000, ge=1, le=1_000_000)


class AdaptiveDecisionConfig(BaseSettings):
    """V2.1 结构化决策、证据引用与有限恢复上限。"""

    enabled: bool = True
    enforce_managed_mutations: bool = False
    max_options: int = Field(default=5, ge=1, le=10)
    max_evidence_refs: int = Field(default=50, ge=1, le=200)
    delivery_retry_limit: int = Field(default=2, ge=0, le=5)
    worker_correction_limit: int = Field(default=1, ge=0, le=3)


class MatrixConfig(BaseSettings):
    """AgentRig Bridge 使用的 Matrix Client-Server API 配置。"""

    homeserver_url: str = ""
    access_token_ref: str | None = None
    bridge_user_id: str = ""
    manager_user_id: str = ""
    curator_user_id: str = ""
    judge_user_id: str = ""
    default_worker_room_id: str = ""
    request_timeout_seconds: float = Field(default=15.0, gt=0)

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
    # 额外允许到达角色 MCP 的 Host header；供 Higress 等受信反向代理使用。
    # 留空时 FastMCP 只允许 localhost，避免无意关闭 DNS rebinding 防护。
    mcp_allowed_hosts: list[str] = Field(default_factory=list)

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
    target_network: TargetNetworkConfig = Field(default_factory=TargetNetworkConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    adaptive_decisions: AdaptiveDecisionConfig = Field(
        default_factory=AdaptiveDecisionConfig
    )
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
            TomlConfigSettingsSource(
                settings_cls,
                toml_file=(
                    os.environ.get("AGENTRIG_CONFIG_FILE")
                    or settings_cls.model_config.get("toml_file")
                    or "agentrig.toml"
                ),
            ),
            dotenv_settings,
            file_secret_settings,
        )


def get_settings() -> Settings:
    """加载并返回配置（暂未缓存，需要时再加 lru_cache）。"""
    return Settings()
