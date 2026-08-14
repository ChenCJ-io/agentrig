"""run_cases、查询、快照和事件的协议契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..capabilities.schemas import TargetCapabilitySnapshot
from ..cases.schemas import CaseSelector
from ..evaluations.models import EvaluationOutcome, EvaluatorType
from ..evaluations.schemas import EvaluationResult
from ..profiles.models import ToolMode
from ..targets.schemas import TargetCreate
from .manifest import RunManifest
from .models import CaseRunStatus, FailureClass, RunEventType, RunStatus


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
    expected_manifest_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

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


class RunCellRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    override_behavior_fail: bool = False

    @model_validator(mode="after")
    def normalize_selection(self) -> RunCellRetryRequest:
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError("reason cannot be blank")
        self.cell_ids = [item.strip() for item in self.cell_ids]
        if any(not item for item in self.cell_ids):
            raise ValueError("cell_ids cannot contain blanks")
        if len(self.cell_ids) != len(set(self.cell_ids)):
            raise ValueError("cell_ids cannot contain duplicates")
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
    manifest_hash: str | None = None
    cell_count: int = 0
    attempt_count: int = 0
    skipped_items: list[SkippedItem] = Field(default_factory=list)


class RunRecoveryResult(RunSubmitResult):
    recovery_of_run_id: str
    recovery_reason: str
    selected_cell_ids: list[str]


class RunPreview(BaseModel):
    """不创建 Run 的只读展开结果，供 EvaluationPlan 预览和提交复核。"""

    resolved_case_ids: list[str]
    planned_case_runs: int
    skipped_items: list[SkippedItem] = Field(default_factory=list)
    profile_snapshot: dict[str, Any]
    target_snapshots: list[dict[str, Any]]
    primary_evaluators: list[EvaluatorType] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    manifest_schema_version: str
    manifest_hash: str
    manifest: RunManifest
    cell_count: int
    attempt_count: int


class RunView(BaseModel):
    id: str
    status: RunStatus
    selection_snapshot: dict[str, Any]
    resolved_case_ids: list[str]
    profile_snapshot: dict[str, Any]
    target_snapshots: list[dict[str, Any]]
    manifest_schema_version: str | None = None
    manifest_hash: str | None = None
    manifest: RunManifest | None = None
    recovery_of_run_id: str | None = None
    recovery_reason: str | None = None
    cell_count: int = 0
    attempt_count: int = 0
    finished_attempt_count: int = 0
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
    cell_key: str = ""
    attempt_id: str = ""
    attempt_index: int = 1
    status: CaseRunStatus
    primary_evaluator: EvaluatorType
    evaluation_state: EvaluationOutcome
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    failure_class: FailureClass | None = None
    recovery_of_case_run_id: str | None = None
    summary: dict[str, Any]


class CaseRunPage(BaseModel):
    items: list[CaseRunSummary]
    total: int
    limit: int
    offset: int


class RunCellSummary(BaseModel):
    cell_id: str
    cell_key: str
    run_id: str
    case_id: str
    target_id: str
    target_role: Literal["baseline", "candidate"]
    version: str | None
    status: CaseRunStatus
    evaluation_state: EvaluationOutcome
    failure_class: FailureClass | None = None
    attempt_count: int
    finished_attempt_count: int
    attempts: list[CaseRunSummary] = Field(default_factory=list)


class RunCellPage(BaseModel):
    items: list[RunCellSummary]
    total: int
    limit: int
    offset: int


class RunProgressSummary(BaseModel):
    """适合轮询和 MCP 上下文的紧凑 Run 投影。"""

    schema_version: Literal["agentrig.batch-run-summary.v1"] = (
        "agentrig.batch-run-summary.v1"
    )
    run_id: str
    status: RunStatus
    terminal: bool
    manifest_hash: str | None = None
    recovery_of_run_id: str | None = None
    cell_count: int
    attempt_count: int
    finished_attempt_count: int
    cells_by_status: dict[str, int] = Field(default_factory=dict)
    attempts_by_status: dict[str, int] = Field(default_factory=dict)
    evaluation_outcomes: dict[str, int] = Field(default_factory=dict)
    failure_classes: dict[str, int] = Field(default_factory=dict)


class RunEvent(BaseModel):
    id: str
    case_run_id: str
    seq: int
    event_type: RunEventType
    attempt_id: str | None = None
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
    capability_snapshot: TargetCapabilitySnapshot | None = None
    events: list[RunEvent] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)


class EvidenceTimelineItem(BaseModel):
    """面向 UI/MCP 的统一证据时间线投影，原始事件仍保持 append-only。"""

    id: str
    cell_id: str
    attempt_id: str
    case_run_id: str
    attempt_index: int
    source_type: Literal["event", "evaluation"]
    source_id: str
    category: str
    actor: str
    status: str | None = None
    title: str
    summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class RunCellDetail(RunCellSummary):
    attempt_details: list[CaseRunDetail] = Field(default_factory=list)
    timeline: list[EvidenceTimelineItem] = Field(default_factory=list)
