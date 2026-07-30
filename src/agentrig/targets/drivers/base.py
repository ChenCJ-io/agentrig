"""所有被测 Agent 协议都要归一到的 Driver 契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class DriverEventType(StrEnum):
    REQUEST_STARTED = "request_started"
    REQUEST_COMPLETED = "request_completed"
    SESSION_STARTED = "session_started"
    ASSISTANT_TEXT_DELTA = "assistant_text_delta"
    ASSISTANT_MESSAGE_COMPLETED = "assistant_message_completed"
    TOOL_CALLS = "tool_calls"
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

    type: DriverEventType
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
    streaming: bool = False
    multi_turn: bool = False
    tool_call_observation: bool = False
    tool_result_injection: bool = False
    session_resume: bool = False
    usage_metrics: bool = False
    full_trace: bool = False
    tool_proxy_injection: bool = False

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
