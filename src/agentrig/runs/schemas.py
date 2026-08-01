"""run_cases、查询、快照和事件的协议契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..cases.schemas import CaseSelector
from ..evaluations.models import EvaluationOutcome, EvaluatorType
from ..evaluations.schemas import EvaluationResult
from ..profiles.models import ToolMode
from ..targets.schemas import TargetCreate
from .models import CaseRunStatus, RunEventType, RunStatus


class RunTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["baseline", "candidate"] = "candidate"
    target_id: str | None = None
    inline_target: TargetCreate | None = None
    version: str | None = None

    @model_validator(mode="after")
    def exactly_one_target_source(self) -> RunTargetInput:
        if (self.target_id is None) == (self.inline_target is None):
            raise ValueError("provide exactly one of target_id or inline_target")
        return self


class RunOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int | None = Field(default=None, ge=1)
    case_timeout_seconds: float | None = Field(default=None, gt=0)
    component_timeouts: dict[str, float] | None = None
    tool_mode: ToolMode | None = None
    provider_chain: list[dict[str, Any]] | None = None
    primary_evaluator: EvaluatorType | None = None


class RunCasesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ids: list[str] | None = None
    selector: CaseSelector | None = None
    targets: list[RunTargetInput] = Field(min_length=1, max_length=2)
    profile_id: str | None = None
    overrides: RunOverrides = Field(default_factory=RunOverrides)
    repeat_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_selection_and_targets(self) -> RunCasesRequest:
        if bool(self.case_ids) == (self.selector is not None):
            raise ValueError("provide exactly one of non-empty case_ids or selector")
        if self.case_ids and len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("case_ids cannot contain duplicates")
        if len(self.targets) == 2:
            roles = {target.role for target in self.targets}
            if roles != {"baseline", "candidate"}:
                raise ValueError("A/B targets require baseline and candidate roles")
        elif self.targets[0].role != "candidate":
            raise ValueError("a normal run target role must be candidate")
        return self


class SkippedItem(BaseModel):
    case_id: str
    target_role: Literal["baseline", "candidate"]
    version: str | None
    repeat_index: int
    comparison_pair_id: str | None = None
    code: str
    message: str


class RunSubmitResult(BaseModel):
    run_id: str
    status: RunStatus
    resolved_case_ids: list[str]
    planned_case_runs: int
    skipped_items: list[SkippedItem] = Field(default_factory=list)


class RunPreview(BaseModel):
    """不创建 Run 的只读展开结果，供 EvaluationPlan 预览和提交复核。"""

    resolved_case_ids: list[str]
    planned_case_runs: int
    skipped_items: list[SkippedItem] = Field(default_factory=list)
    profile_snapshot: dict[str, Any]
    target_snapshots: list[dict[str, Any]]
    primary_evaluators: list[EvaluatorType] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)


class RunView(BaseModel):
    id: str
    status: RunStatus
    selection_snapshot: dict[str, Any]
    resolved_case_ids: list[str]
    profile_snapshot: dict[str, Any]
    target_snapshots: list[dict[str, Any]]
    total_count: int
    completed_count: int
    failed_count: int
    skipped_count: int
    cancelled_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class RunPage(BaseModel):
    items: list[RunView]
    total: int
    limit: int
    offset: int


class CaseRunSummary(BaseModel):
    id: str
    run_id: str
    case_id: str
    version: str | None
    repeat_index: int
    comparison_pair_id: str | None
    comparison_role: Literal["baseline", "candidate"] | None
    status: CaseRunStatus
    primary_evaluator: EvaluatorType
    evaluation_state: EvaluationOutcome
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    summary: dict[str, Any]


class CaseRunPage(BaseModel):
    items: list[CaseRunSummary]
    total: int
    limit: int
    offset: int


class RunEvent(BaseModel):
    id: str
    case_run_id: str
    seq: int
    event_type: RunEventType
    payload: dict[str, Any]
    created_at: datetime


class RunEventPage(BaseModel):
    items: list[RunEvent]
    total: int
    limit: int
    offset: int


class CaseRunDetail(CaseRunSummary):
    case_snapshot: dict[str, Any]
    target_snapshot: dict[str, Any]
    profile_snapshot: dict[str, Any]
    events: list[RunEvent] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)
