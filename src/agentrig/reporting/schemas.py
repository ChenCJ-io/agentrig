"""报告和导出的稳定服务端契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..evaluations.models import EvaluationOutcome
from ..runs.models import CaseRunStatus, RunStatus


class RunReportTarget(BaseModel):
    id: str
    name: str
    version: str | None = None


class RunReportRun(BaseModel):
    id: str
    status: RunStatus
    resolved_case_ids: list[str]
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


class RunOutcomeCounts(BaseModel):
    total: int
    evaluated: int
    pass_count: int
    fail_count: int
    inconclusive_count: int
    awaiting_verdict_count: int
    evaluation_error_count: int


class RunReportFailure(BaseModel):
    id: str
    case_id: str
    version: str | None
    repeat_index: int
    status: CaseRunStatus
    evaluation_state: EvaluationOutcome
    error_code: str | None
    error_message: str | None
    evaluation_summary: str | None


class RunReport(BaseModel):
    schema_version: Literal["agentrig.run-report.v1"] = "agentrig.run-report.v1"
    generated_at: datetime
    run: RunReportRun
    targets: list[RunReportTarget] = Field(default_factory=list)
    outcomes: RunOutcomeCounts
    failures: list[RunReportFailure] = Field(default_factory=list)


class ExportCounts(BaseModel):
    runs: int
    test_cases: int
    samples: int
    total_records: int


class TargetExportPreview(BaseModel):
    schema_version: Literal["agentrig.export-preview.v1"] = (
        "agentrig.export-preview.v1"
    )
    target_id: str
    counts: ExportCounts
    max_export_records: int
    within_limit: bool


class TargetExportScope(BaseModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    samples: list[dict[str, Any]] = Field(default_factory=list)


class TargetExportBundle(BaseModel):
    schema_version: Literal["agentrig.export.v1"] = "agentrig.export.v1"
    target_id: str
    generated_at: datetime
    target: dict[str, Any]
    counts: ExportCounts
    scope: TargetExportScope
    redaction: str
