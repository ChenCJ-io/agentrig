"""Manager 决策提案、证据引用与查询契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .decision_models import (
    DecisionActionType,
    DecisionKind,
    DecisionStatus,
    DecisionTrigger,
    PolicyVerdictType,
)


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=300)
    version: str | None = Field(default=None, max_length=128)
    snapshot_hash: str | None = Field(default=None, max_length=128)
    label: str | None = Field(default=None, max_length=300)


class DecisionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: DecisionActionType
    label: str = Field(min_length=1, max_length=300)
    expected_effect: str = Field(default="", max_length=500)


class DecisionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: DecisionActionType
    parameters: dict[str, Any] = Field(default_factory=dict)


class ObservationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    known: list[str] = Field(default_factory=list, max_length=20)
    unknown: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)


class RationaleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2_000)
    tradeoffs: list[str] = Field(default_factory=list, max_length=10)


class ManagerDecisionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="agentrig.manager-decision.v1", max_length=64)
    session_id: str
    turn_id: str
    parent_decision_id: str | None = None
    trigger: DecisionTrigger
    decision_kind: DecisionKind
    objective: str = Field(min_length=1, max_length=500)
    observation_summary: ObservationSummary
    options: list[DecisionOption] = Field(min_length=1, max_length=10)
    selected_action: DecisionAction
    rationale_summary: RationaleSummary
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    proposed_by: str = Field(default="agentteams_manager", min_length=1, max_length=300)

    @model_validator(mode="after")
    def selected_action_is_an_option(self) -> ManagerDecisionProposal:
        if self.selected_action.action_type not in {item.action_type for item in self.options}:
            raise ValueError("selected_action must match one of the proposed options")
        return self


class PolicyVerdict(BaseModel):
    verdict: PolicyVerdictType
    reasons: list[str] = Field(default_factory=list)
    rule_version: str = "agentrig.decision-policy.v1"


class DecisionRecordView(BaseModel):
    id: str
    session_id: str
    turn_id: str
    parent_decision_id: str | None
    ordinal: int
    schema_version: str
    trigger: DecisionTrigger
    decision_kind: DecisionKind
    status: DecisionStatus
    objective: str
    observation_summary: ObservationSummary
    options: list[DecisionOption]
    selected_action: DecisionAction
    rationale_summary: RationaleSummary
    evidence_refs: list[EvidenceRef]
    confidence: float | None
    context_hash: str
    policy_verdict: PolicyVerdict
    confirmation_event_id: str | None
    action_idempotency_key: str | None
    action_ref_type: str | None
    action_ref_id: str | None
    error_code: str | None
    error_message: str | None
    proposed_by: str
    created_at: datetime
    authorized_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class DecisionRecordPage(BaseModel):
    items: list[DecisionRecordView]
    total: int
    limit: int
    offset: int


class DecisionQualityMetrics(BaseModel):
    decision_count: int
    terminal_count: int
    succeeded_count: int
    failed_count: int
    in_flight_count: int
    success_rate: float | None
    evidence_reference_count: int
    evidence_kind_coverage: list[str]
    confirmation_bound_count: int
    provenance_linked_count: int
    provenance_link_rate: float | None
    latest_decision_at: datetime | None


class DecisionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_event_id: str


class DecisionCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="cancelled by user", max_length=500)
