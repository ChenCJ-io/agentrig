"""所有被测 Agent 协议都要归一到的 Driver 契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class DriverEventType(StrEnum):
    REQUEST_STARTED = "request_started"
    REQUEST_COMPLETED = "request_completed"
    SESSION_STARTED = "session_started"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    ASSISTANT_MESSAGE_COMPLETED = "assistant_message_completed"
    TOOL_CALLS = "tool_calls"
    SESSION_STATUS_CHANGED = "session_status_changed"
    MODEL_CALL_STARTED = "model_call_started"
    MODEL_CALL_COMPLETED = "model_call_completed"
    THINKING_STARTED = "thinking_started"
    THINKING_DELTA = "thinking_delta"
    THINKING_COMPLETED = "thinking_completed"
    DATA_PART = "data_part"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_ARGUMENTS_DELTA = "tool_call_arguments_delta"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_RESULT_OBSERVED = "tool_result_observed"
    PERMISSION_REQUESTED = "permission_requested"
    PERMISSION_RESOLVED = "permission_resolved"
    EXTERNAL_EXECUTION_REQUESTED = "external_execution_requested"
    EXTERNAL_EXECUTION_RESOLVED = "external_execution_resolved"
    INTERRUPT_REQUESTED = "interrupt_requested"
    INTERRUPTED = "interrupted"
    RESUMED = "resumed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    MEMORY_OPERATION = "memory_operation"
    WORKSPACE_ARTIFACT = "workspace_artifact"
    USAGE = "usage"
    COMPLETED = "completed"
    ERROR = "error"


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_schema: dict[str, Any] | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    result: Any
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DriverEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agentrig.driver-event.v2"] = "agentrig.driver-event.v2"
    event_id: str | None = None
    type: DriverEventType
    occurred_at: datetime | None = None
    sequence: int | None = Field(default=None, ge=0)
    parent_event_id: str | None = None
    agent_path: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_type: str | None = None
    source: str | None = None
    redaction: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    request_id: str | None = None
    request_kind: str | None = None
    request_status: str | None = None
    duration_ms: float | None = None
    ttft_ms: float | None = None
    text: str | None = None
    refusal: bool = False
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DriverCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    streaming: bool = False
    multi_turn: bool = False
    tool_call_observation: bool = False
    tool_result_injection: bool = False
    session_resume: bool = False
    usage_metrics: bool = False
    full_trace: bool = False
    tool_proxy_injection: bool = False
    permission_observation: bool = False
    permission_response: bool = False
    interrupt: bool = False
    resume: bool = False
    external_execution: bool = False
    nested_agents: bool = False
    model_call_observation: bool = False
    memory_observation: bool = False
    workspace_artifacts: bool = False
    multimodal: bool = False
    ordered_event_cursor: bool = False

    def names(self) -> list[str]:
        return [
            name
            for name in type(self).model_fields
            if bool(getattr(self, name))
        ]


class DriverPrepareContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_run_id: str
    target: dict[str, Any]
    version: str | None
    initial_state: dict[str, Any] = Field(default_factory=dict)
    secret_value: str | None = None
    component_timeout_seconds: float = Field(gt=0)
    tool_proxy_url: str | None = None
    tool_proxy_headers: dict[str, str] = Field(default_factory=dict)


class DriverSession(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    id: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class AgentDriver(Protocol):
    def capabilities(self) -> DriverCapabilities: ...

    async def prepare(self, context: DriverPrepareContext) -> DriverSession: ...

    def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]: ...

    def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]: ...

    async def cancel(self, session: DriverSession) -> None: ...

    async def close(self, session: DriverSession) -> None: ...


@runtime_checkable
class ConfigurableAgentDriver(Protocol):
    """可在真正启动 Agent 前校验 Target 配置的 Driver。"""

    def validate_configuration(
        self,
        options: dict[str, Any],
        *,
        secret_configured: bool,
    ) -> None: ...


@runtime_checkable
class ProbeableAgentDriver(Protocol):
    """可执行一次不产生业务对话的真实连通性探针。"""

    async def probe(self, context: DriverPrepareContext) -> None: ...


@runtime_checkable
class DescribableAgentDriver(Protocol):
    """Return public runtime metadata observed before the first user message."""

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, Any]: ...


@runtime_checkable
class ResumableAgentDriver(Protocol):
    def resume(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]: ...


@runtime_checkable
class PermissionResponseAgentDriver(Protocol):
    def submit_permission_response(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]: ...


@runtime_checkable
class ExternalExecutionAgentDriver(Protocol):
    def submit_external_result(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]: ...
