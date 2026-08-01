"""AgentInvocation 与 AgentTeams 任务信封。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .invocation_models import AgentInvocationStatus, AgentRole
from .ports import AgentTaskContext


class AgentInvocationView(BaseModel):
    id: str
    agent_role: AgentRole
    status: AgentInvocationStatus
    session_id: str | None
    plan_id: str | None
    run_id: str
    case_run_id: str
    tool_call_event_id: str | None
    attempt: int
    input_snapshot: dict[str, Any]
    input_hash: str
    result_payload: dict[str, Any] | None
    result_ref: str | None
    result_hash: str | None
    matrix_room_id: str | None
    request_event_id: str | None
    response_event_id: str | None
    assigned_agent: str | None
    deadline: datetime
    idempotency_key: str
    error_code: str | None
    error_message: str | None
    retryable: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AgentInvocationPage(BaseModel):
    items: list[AgentInvocationView]
    total: int
    limit: int
    offset: int


class AgentInvocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AgentRole
    context: AgentTaskContext
    attempt: int = Field(default=1, ge=1)
    input_snapshot: dict[str, Any]
    deadline: datetime
    idempotency_key: str
    matrix_room_id: str | None = None


class AgentTaskEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agentrig.agent-task.v1"
    task_id: str
    role: AgentRole
    target_role: str
    case_run_id: str
    run_id: str
    input_ref: str
    deadline: datetime
    attempt: int
    input_hash: str
    callback_tool: str


class AgentResultSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str
    result: dict[str, Any]
    response_event_id: str | None = None


class AgentInvocationFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_code: str
    error_message: str
    retryable: bool = False
    response_event_id: str | None = None
