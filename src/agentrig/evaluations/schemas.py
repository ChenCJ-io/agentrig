"""三个评判来源共用的持久化输出结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import EvaluationOutcome, EvaluationRecordStatus, EvaluatorType


class EvaluationCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    verdict: Literal["pass", "fail", "inconclusive"]
    evidence_refs: list[str] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    case_run_id: str
    evaluator_type: EvaluatorType
    evaluator_source: str
    status: EvaluationRecordStatus
    verdict: Literal["pass", "fail", "inconclusive"] | None = None
    summary: str
    criteria: list[EvaluationCriterion] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ExternalVerdictSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail", "inconclusive"]
    summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(
        default_factory=list,
        description=(
            "可选的证据引用；每一项必须是 get_case_run.events[].id 或 "
            "list_case_run_events.items[].id。"
        ),
    )
    submitted_by: str = "external_controller"


class EvaluationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EvaluationRecordStatus = EvaluationRecordStatus.COMPLETED
    verdict: Literal["pass", "fail", "inconclusive"] | None = None
    summary: str
    criteria: list[EvaluationCriterion] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationResolution(BaseModel):
    outcome: EvaluationOutcome
    primary_evaluator: EvaluatorType
    resolved_from: EvaluatorType | None = None
