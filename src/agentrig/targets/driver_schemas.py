"""内置 Driver 的可发现 Target options 契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCatalogItem(BaseModel):
    """被测 Agent 会通过 CaseRun MCP Proxy 看到的一个工具。"""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        alias="inputSchema",
    )
    output_schema: dict[str, Any] | None = Field(
        default=None,
        alias="outputSchema",
    )


class AcpTargetOptions(BaseModel):
    """stdio ACP Target 的完整 V1 options。"""

    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(
        min_length=1,
        description=(
            "ACP 启动命令数组；第一项必须是部署 subprocess_allowlist 允许的"
            "可执行文件。相对路径按 cwd 解析。"
        ),
    )
    cwd: str | None = Field(
        default=None,
        description="ACP 子进程的宿主机工作目录。",
    )
    session_cwd: str = Field(
        default="/workspace",
        min_length=1,
        description="传给 ACP session/new 的 Agent 工作目录。",
    )
    credential_env: str | None = Field(
        default=None,
        description=(
            "把 Target secret_ref 解析后的值注入 ACP 子进程时使用的环境变量名。"
        ),
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="不含凭据的 ACP 子进程环境变量覆盖。",
    )
    permission_mode: Literal["deny", "allow_once"] = "deny"
    mcp_server_name: str = Field(default="agentrig-case-tools", min_length=1)
    isolation_root: str | None = Field(
        default=None,
        description="可选的 CaseRun 独立运行目录根路径。",
    )
    isolation_env: str | None = Field(
        default=None,
        description="把 CaseRun 独立目录传给 ACP 子进程时使用的环境变量名。",
    )
    shutdown_timeout_seconds: float = Field(default=2.0, gt=0)
    tool_catalog: list[ToolCatalogItem] = Field(
        default_factory=list,
        description=(
            "当被测 Agent 没有业务 MCP Server，且用例依赖 Sample/Curator 时，"
            "显式声明可发现工具及其 JSON Schema。"
        ),
    )


class AgUiTargetOptions(BaseModel):
    """Public AG-UI transport and runtime metadata options."""

    model_config = ConfigDict(extra="forbid")

    run_path: str = ""
    health_path: str = "/health"
    cancel_path: str | None = None
    capability_path: str = "/capabilities"
    capability_probe: bool = True
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    request_headers: dict[str, str] = Field(default_factory=dict)
    thread_id: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    context: list[dict[str, Any]] = Field(default_factory=list)
    forwarded_props: dict[str, Any] = Field(default_factory=dict)
    framework: str = "ag-ui"
    framework_version: str | None = None
    protocol_version: str = "1"
    max_reconnects: int = Field(default=1, ge=0, le=10)
    max_event_bytes: int = Field(
        default=256 * 1_024,
        ge=1_024,
        le=4 * 1_024 * 1_024,
    )
    max_events: int = Field(default=10_000, ge=1, le=100_000)
    runtime: dict[str, Any] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    permission_mode: str | None = None
    workspace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    collaboration: dict[str, Any] = Field(default_factory=dict)


class PythonAgentTargetOptions(BaseModel):
    """在被测 Agent 自己的 Python 解释器里运行 AgentRig harness 的 options。"""

    model_config = ConfigDict(extra="forbid")

    entry: str = Field(
        pattern=r"^(?:[A-Za-z_][\w.]*|.+\.py):[A-Za-z_][\w.]*$",
        description=(
            "module:attribute 或 path/to/file.py:attribute，指向 Agno Agent/Team、"
            "LangGraph 编译图或 callable(messages)。"
        ),
    )
    python: str = Field(
        min_length=1,
        description="被测 Agent 虚拟环境里的 Python 解释器；必须在部署 subprocess_allowlist 中。",
    )
    cwd: str | None = Field(
        default=None,
        description="被测项目根目录，用于导入 entry 模块和读取项目自己的 .env。",
    )
    adapter: Literal["auto", "agno", "langgraph", "callable"] = "auto"
    factory: bool = Field(
        default=False,
        description="entry 是无参工厂函数时，先调用它构建 Agent。",
    )
    credential_env: str | None = Field(
        default=None,
        description="把 Target secret_ref 解析后的值注入被测进程时使用的环境变量名。",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="不含凭据的被测进程环境变量覆盖。",
    )
    inherit_env: list[str] = Field(
        default_factory=list,
        description=(
            "从 AgentRig 进程原样转发的环境变量名。被测进程默认只继承 PATH、HOME、"
            "语言、代理和证书等基础变量，AgentRig 自身的 Secret 不会泄漏给被测代码。"
        ),
    )
    startup_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
        description="导入被测 Agent 并完成 harness 握手的最长时间。",
    )
    conversation_initial_state: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "「对话验证」会话的初始状态，同时交给被测 Agent 和 Simulation Curator；"
            "可以描述业务世界，让模拟的工具结果贴近真实数据。"
        ),
    )


def options_schema(driver_type: str) -> dict[str, Any] | None:
    """返回内置 Driver 的 options JSON Schema。"""

    if driver_type == "acp":
        return AcpTargetOptions.model_json_schema(by_alias=True)
    if driver_type in {"ag_ui", "agentscope"}:
        schema = AgUiTargetOptions.model_json_schema(by_alias=True)
        if driver_type == "agentscope":
            schema["title"] = "AgentScopeTargetOptions"
        return schema
    if driver_type == "python_agent":
        return PythonAgentTargetOptions.model_json_schema(by_alias=True)
    return None


def options_example(driver_type: str) -> dict[str, Any] | None:
    """返回不含部署路径或凭据的最小配置示例。"""

    if driver_type == "acp":
        return {
            "command": ["/absolute/path/to/agent/run-acp.sh"],
            "cwd": "/absolute/path/to/agent",
            "session_cwd": "/workspace",
            "credential_env": "MODEL_API_KEY",
            "env": {
                "AGENT_PROVIDER": "provider-name",
                "AGENT_MODEL": "model-name",
            },
            "isolation_root": "/absolute/path/to/case-runtimes",
            "isolation_env": "AGENT_RUNTIME_DIR",
            "tool_catalog": [
                {
                    "name": "lookup_item",
                    "description": "Look up an item by ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"item_id": {"type": "string"}},
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                }
            ],
        }
    if driver_type in {"ag_ui", "agentscope"}:
        return {
            "run_path": "/ag-ui",
            "health_path": "/health",
            "capability_path": "/capabilities",
            "framework": "agentscope" if driver_type == "agentscope" else "ag-ui",
            "framework_version": "2.0.6" if driver_type == "agentscope" else None,
            "protocol_version": "1",
        }
    if driver_type == "python_agent":
        return {
            "entry": "my_app.agent:agent",
            "python": "/absolute/path/to/agent/.venv/bin/python",
            "cwd": "/absolute/path/to/agent",
            "credential_env": "MODEL_API_KEY",
        }
    return None
