"""Public durable job and lease contracts; token hashes are never projected."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal[
    "queued", "leased", "running", "completed", "failed", "cancelled", "dead"
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExecutionJobCreate(_StrictModel):
    run_id: str
    case_run_id: str
    priority: int = Field(default=0, ge=-1_000, le=1_000)
    available_at: datetime | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ExecutionJobView(_StrictModel):
    id: str
    project_id: str
    run_id: str
    case_run_id: str
    status: JobStatus
    priority: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    attempt: int
    max_attempts: int
    idempotency_key: str
    external_side_effect: bool
    cancel_requested_at: datetime | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


class ExecutionJobPage(_StrictModel):
    items: list[ExecutionJobView]
    total: int
    limit: int
    offset: int


class ExecutionAttemptView(_StrictModel):
    id: str
    project_id: str
    job_id: str
    attempt: int
    lease_owner: str
    status: Literal[
        "leased", "running", "completed", "failed", "cancelled", "interrupted"
    ]
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    external_side_effect: bool


class JobLease(_StrictModel):
    job: ExecutionJobView
    attempt: ExecutionAttemptView
    lease_token: str


class ReaperResult(_StrictModel):
    inspected: int
    requeued: int
    dead: int
    side_effect_dead: int


class WorkerRegistrationView(_StrictModel):
    worker_id: str
    backend: Literal["sqlite", "postgresql"]
    started_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
