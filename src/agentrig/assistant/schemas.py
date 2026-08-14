"""智能评测助手和 EvaluationPlan 的 HTTP/MCP 共用契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..runs.schemas import RunCasesRequest, RunPreview
from .models import (
    ActorType,
    AssistantEventType,
    AssistantSessionStatus,
    AssistantTurnStatus,
    DeliveryStatus,
    EvaluationPlanStatus,
)


class AssistantSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    workspace_id: str = Field(default="default", min_length=1, max_length=96)


class AssistantSessionView(BaseModel):
    id: str
    workspace_id: str
    title: str
    status: AssistantSessionStatus
    matrix_room_id: str | None
    active_plan_id: str | None
    last_event_seq: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class AssistantSessionPage(BaseModel):
    items: list[AssistantSessionView]
    total: int
    limit: int
    offset: int


class AssistantPlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: Literal["confirm_plan", "submit_plan", "cancel_plan"]
    plan_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)


class AssistantMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=100_000)
    active_plan_id: str | None = None
    plan_action: AssistantPlanAction | None = None


class AssistantMessageReceipt(BaseModel):
    event_id: str
    turn_id: str
    delivery_status: DeliveryStatus


class BasicAssistantOutput(BaseModel):
    """基础模型只提出回答、澄清或 Plan 草稿，执行仍由 Core 完成。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["answer", "clarify", "create_plan"]
    content: str = Field(min_length=1, max_length=10_000)
    goal: dict[str, Any] | None = None
    selection: RunCasesRequest | None = None


class AssistantProviderHealth(BaseModel):
    enabled: bool
    available: bool
    provider: Literal["agentteams", "openai_compatible", "none"]
    message: str


class AssistantEventView(BaseModel):
    id: str
    session_id: str
    seq: int
    event_type: AssistantEventType
    actor_type: ActorType
    actor_id: str
    payload: dict[str, Any]
    turn_id: str | None
    plan_id: str | None
    run_id: str | None
    case_run_id: str | None
    invocation_id: str | None
    decision_id: str | None
    client_message_id: str | None
    matrix_event_id: str | None
    delivery_status: DeliveryStatus
    delivery_attempts: int
    last_error: str | None
    created_at: datetime


class AssistantEventPage(BaseModel):
    items: list[AssistantEventView]
    total: int
    limit: int
    after_seq: int


class AssistantTurnView(BaseModel):
    id: str
    session_id: str
    trigger_event_id: str
    status: AssistantTurnStatus
    matrix_request_event_id: str | None
    matrix_response_event_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    model_metadata: dict[str, Any]
    created_at: datetime


class EvaluationPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    source_turn_id: str
    parent_plan_id: str | None = None
    origin_decision_id: str | None = None
    goal: dict[str, Any]
    selection: RunCasesRequest
    reasoning_summary: dict[str, Any] = Field(default_factory=dict)
    created_by: str


class EvaluationPlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: dict[str, Any] | None = None
    selection: RunCasesRequest | None = None
    reasoning_summary: dict[str, Any] | None = None
    decision_id: str | None = None


class PlanConfirmation(BaseModel):
    required: bool = False
    reasons: list[str] = Field(default_factory=list)
    confirmation_event_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class EvaluationPlanView(BaseModel):
    id: str
    session_id: str
    source_turn_id: str
    parent_plan_id: str | None
    origin_decision_id: str | None
    revision: int
    status: EvaluationPlanStatus
    goal: dict[str, Any]
    selection: dict[str, Any]
    reasoning_summary: dict[str, Any]
    preview: dict[str, Any]
    confirmation: PlanConfirmation
    selection_hash: str | None
    submit_idempotency_key: str | None
    run_id: str | None
    last_error: dict[str, Any] | None
    created_by: str
    confirmed_by: str | None
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    submitted_at: datetime | None

    def run_request(self) -> RunCasesRequest:
        return RunCasesRequest.model_validate(self.selection)


class EvaluationPlanValidation(BaseModel):
    plan: EvaluationPlanView
    preview: RunPreview


class EvaluationPlanConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_event_id: str
    confirmed_by: str
    decision_id: str | None = None


class EvaluationPlanSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=128)
    decision_id: str | None = None
