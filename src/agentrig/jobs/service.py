"""Database-backed claim/lease protocol and bounded worker execution."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from ..config import ExecutionConfig
from ..errors import AgentRigError, ErrorCode
from ..evaluations.models import EvaluationOutcome
from ..identifiers import new_id
from ..infrastructure.database.orm import (
    CaseRunORM,
    EvaluationPlanORM,
    ExecutionAttemptORM,
    ExecutionJobORM,
    RunORM,
    WorkerRegistrationORM,
    utc_now,
)
from ..infrastructure.database.session import Database
from ..runs.event_recorder import execution_attempt
from ..runs.executor import CaseExecutor
from ..runs.models import CaseRunStatus, RunStatus
from ..runs.repository import RunRepository
from ..runs.schemas import RunView
from .schemas import (
    ExecutionAttemptView,
    ExecutionJobCreate,
    ExecutionJobPage,
    ExecutionJobView,
    JobLease,
    ReaperResult,
    WorkerRegistrationView,
)

logger = logging.getLogger("agentrig.jobs.worker")
RunCompletionListener = Callable[[RunView], Awaitable[None]]


class DurableJobService:
    def __init__(self, database: Database, config: ExecutionConfig) -> None:
        self._database = database
        self._config = config
        self._sqlite_claim_lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "sqlite" if self._database.url.startswith("sqlite") else "postgresql"

    async def enqueue(self, project_id: str, value: ExecutionJobCreate) -> ExecutionJobView:
        try:
            async with self._database.session() as session:
                case_run = await session.scalar(
                    select(CaseRunORM).where(
                        CaseRunORM.id == value.case_run_id,
                        CaseRunORM.run_id == value.run_id,
                        CaseRunORM.project_id == project_id,
                    )
                )
                if case_run is None:
                    raise AgentRigError(ErrorCode.NOT_FOUND, "run/case run pair not found")
                existing = await session.scalar(
                    select(ExecutionJobORM).where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.idempotency_key == value.idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.run_id != value.run_id or existing.case_run_id != value.case_run_id:
                        raise AgentRigError(ErrorCode.CONFLICT, "job idempotency conflict")
                    return self._job_view(existing)
                run = await session.scalar(
                    select(RunORM).where(
                        RunORM.id == value.run_id,
                        RunORM.project_id == project_id,
                    )
                )
                if run is None:
                    raise AgentRigError(ErrorCode.NOT_FOUND, "durable run not found")
                if run.status in {
                    RunStatus.COMPLETED.value,
                    RunStatus.CANCELLED.value,
                    RunStatus.INTERRUPTED.value,
                    RunStatus.FAILED.value,
                }:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "cannot enqueue a job for a terminal run",
                    )
                if case_run.status != CaseRunStatus.QUEUED.value:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "durable execution requires a queued case run",
                    )
                duplicate_case_run = await session.scalar(
                    select(ExecutionJobORM).where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.case_run_id == value.case_run_id,
                    )
                )
                if duplicate_case_run is not None:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "case run already has a durable execution job",
                    )
                row = self._new_job(project_id, value)
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return self._job_view(row)
        except IntegrityError as exc:
            # Unique constraints are the final authority when two API requests
            # enqueue the same CaseRun concurrently.
            async with self._database.session() as session:
                existing = await session.scalar(
                    select(ExecutionJobORM).where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.idempotency_key == value.idempotency_key,
                    )
                )
                if (
                    existing is not None
                    and existing.run_id == value.run_id
                    and existing.case_run_id == value.case_run_id
                ):
                    return self._job_view(existing)
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "case run already has a durable execution job",
            ) from exc

    async def enqueue_plan(
        self, project_id: str, run_id: str, case_run_ids: list[str]
    ) -> list[ExecutionJobView]:
        if len(case_run_ids) != len(set(case_run_ids)):
            raise AgentRigError(ErrorCode.CONFLICT, "duplicate case run in plan")
        if not case_run_ids:
            return []
        try:
            async with self._database.session() as session:
                run = await session.scalar(
                    select(RunORM).where(
                        RunORM.id == run_id,
                        RunORM.project_id == project_id,
                    )
                )
                if run is None:
                    raise AgentRigError(ErrorCode.NOT_FOUND, "durable run not found")
                case_rows = list(
                    await session.scalars(
                        select(CaseRunORM).where(
                            CaseRunORM.project_id == project_id,
                            CaseRunORM.run_id == run_id,
                            CaseRunORM.id.in_(case_run_ids),
                        )
                    )
                )
                if {row.id for row in case_rows} != set(case_run_ids):
                    raise AgentRigError(ErrorCode.NOT_FOUND, "run/case run plan is incomplete")
                case_by_id = {row.id: row for row in case_rows}
                existing_rows = list(
                    await session.scalars(
                        select(ExecutionJobORM).where(
                            ExecutionJobORM.project_id == project_id,
                            ExecutionJobORM.case_run_id.in_(case_run_ids),
                        )
                    )
                )
                existing_by_case = {row.case_run_id: row for row in existing_rows}
                missing_case_run_ids: list[str] = []
                for case_run_id in case_run_ids:
                    expected_key = f"case-run:{case_run_id}"
                    existing = existing_by_case.get(case_run_id)
                    if existing is not None:
                        if existing.run_id != run_id or existing.idempotency_key != expected_key:
                            raise AgentRigError(
                                ErrorCode.CONFLICT,
                                "case run already has a conflicting execution job",
                            )
                        continue
                    missing_case_run_ids.append(case_run_id)
                if not missing_case_run_ids:
                    return [
                        self._job_view(existing_by_case[case_run_id])
                        for case_run_id in case_run_ids
                    ]
                if run.status in {
                    RunStatus.COMPLETED.value,
                    RunStatus.CANCELLED.value,
                    RunStatus.INTERRUPTED.value,
                    RunStatus.FAILED.value,
                }:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "cannot dispatch a terminal run",
                    )
                if any(
                    case_by_id[item].status != CaseRunStatus.QUEUED.value
                    for item in missing_case_run_ids
                ):
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "durable plan contains a non-queued case run",
                    )
                for case_run_id in missing_case_run_ids:
                    expected_key = f"case-run:{case_run_id}"
                    row = self._new_job(
                        project_id,
                        ExecutionJobCreate(
                            run_id=run_id,
                            case_run_id=case_run_id,
                            idempotency_key=expected_key,
                        ),
                    )
                    session.add(row)
                    existing_by_case[case_run_id] = row
                # All missing jobs become visible together; a failed batch can
                # never expose a partially dispatched Run.
                await session.commit()
                return [
                    self._job_view(existing_by_case[case_run_id]) for case_run_id in case_run_ids
                ]
        except IntegrityError as exc:
            async with self._database.session() as session:
                existing_rows = list(
                    await session.scalars(
                        select(ExecutionJobORM).where(
                            ExecutionJobORM.project_id == project_id,
                            ExecutionJobORM.case_run_id.in_(case_run_ids),
                        )
                    )
                )
                existing_by_case = {row.case_run_id: row for row in existing_rows}
                exact = all(
                    case_run_id in existing_by_case
                    and existing_by_case[case_run_id].run_id == run_id
                    and existing_by_case[case_run_id].idempotency_key == f"case-run:{case_run_id}"
                    for case_run_id in case_run_ids
                )
                if exact:
                    return [
                        self._job_view(existing_by_case[case_run_id])
                        for case_run_id in case_run_ids
                    ]
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "durable plan was concurrently dispatched",
            ) from exc

    def _new_job(self, project_id: str, value: ExecutionJobCreate) -> ExecutionJobORM:
        return ExecutionJobORM(
            id=new_id("job"),
            project_id=project_id,
            run_id=value.run_id,
            case_run_id=value.case_run_id,
            status="queued",
            priority=value.priority,
            available_at=value.available_at or utc_now(),
            attempt=0,
            max_attempts=value.max_attempts or self._config.job_max_attempts,
            idempotency_key=value.idempotency_key,
            external_side_effect=False,
        )

    async def get(self, project_id: str, job_id: str) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(ExecutionJobORM).where(
                    ExecutionJobORM.id == job_id,
                    ExecutionJobORM.project_id == project_id,
                )
            )
        if row is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "execution job not found")
        return self._job_view(row)

    async def list_jobs(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ExecutionJobPage:
        filters: list[Any] = [ExecutionJobORM.project_id == project_id]
        if status:
            filters.append(ExecutionJobORM.status == status)
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(ExecutionJobORM.id)).where(*filters)) or 0
            )
            rows = list(
                await session.scalars(
                    select(ExecutionJobORM)
                    .where(*filters)
                    .order_by(ExecutionJobORM.created_at.desc(), ExecutionJobORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return ExecutionJobPage(
            items=[self._job_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def register_worker(self, worker_id: str) -> WorkerRegistrationView:
        now = utc_now()
        expires = now + timedelta(seconds=self._config.worker_registration_ttl_seconds)
        async with self._database.session() as session:
            if self.backend == "sqlite":
                other = await session.scalar(
                    select(WorkerRegistrationORM).where(
                        WorkerRegistrationORM.id != worker_id,
                        WorkerRegistrationORM.expires_at > now,
                    )
                )
                if other is not None:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "SQLite supports exactly one active durable worker",
                        details={"active_worker_id": other.id},
                    )
            row = await session.get(WorkerRegistrationORM, worker_id)
            if row is None:
                row = WorkerRegistrationORM(
                    id=worker_id,
                    backend=self.backend,
                    started_at=now,
                    heartbeat_at=now,
                    expires_at=expires,
                )
                session.add(row)
            else:
                row.backend = self.backend
                row.heartbeat_at = now
                row.expires_at = expires
            await session.commit()
            await session.refresh(row)
        return self._worker_view(row)

    async def worker_heartbeat(self, worker_id: str) -> WorkerRegistrationView:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.get(WorkerRegistrationORM, worker_id)
            if row is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "worker is not registered")
            row.heartbeat_at = now
            row.expires_at = now + timedelta(seconds=self._config.worker_registration_ttl_seconds)
            await session.commit()
            await session.refresh(row)
        return self._worker_view(row)

    async def unregister_worker(self, worker_id: str) -> None:
        async with self._database.session() as session:
            row = await session.get(WorkerRegistrationORM, worker_id)
            if row is not None:
                row.expires_at = utc_now()
                await session.commit()

    async def claim(
        self,
        worker_id: str,
        *,
        project_id: str | None = None,
        lease_seconds: int | None = None,
    ) -> JobLease | None:
        if self.backend == "sqlite":
            async with self._sqlite_claim_lock:
                return await self._claim_locked(
                    worker_id, project_id=project_id, lease_seconds=lease_seconds
                )
        return await self._claim_locked(
            worker_id, project_id=project_id, lease_seconds=lease_seconds
        )

    async def _claim_locked(
        self,
        worker_id: str,
        *,
        project_id: str | None,
        lease_seconds: int | None,
    ) -> JobLease | None:
        now = utc_now()
        duration = lease_seconds or self._config.job_lease_seconds
        async with self._database.session() as session:
            registration = await session.get(WorkerRegistrationORM, worker_id)
            if registration is None or self._expired(registration.expires_at, now):
                raise AgentRigError(ErrorCode.PERMISSION_DENIED, "worker registration expired")
            query = (
                select(ExecutionJobORM)
                .where(
                    ExecutionJobORM.status == "queued",
                    ExecutionJobORM.available_at <= now,
                    ExecutionJobORM.cancel_requested_at.is_(None),
                )
                .order_by(
                    ExecutionJobORM.priority.desc(),
                    ExecutionJobORM.available_at,
                    ExecutionJobORM.created_at,
                    ExecutionJobORM.id,
                )
                .limit(1)
            )
            if project_id:
                query = query.where(ExecutionJobORM.project_id == project_id)
            if self.backend == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = await session.scalar(query)
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            token_hash = self._token_hash(token)
            row.status = "leased"
            row.lease_owner = worker_id
            row.lease_token_hash = token_hash
            row.lease_expires_at = now + timedelta(seconds=duration)
            row.heartbeat_at = now
            row.attempt += 1
            attempt = ExecutionAttemptORM(
                id=new_id("attempt"),
                project_id=row.project_id,
                job_id=row.id,
                attempt=row.attempt,
                lease_owner=worker_id,
                lease_token_hash=token_hash,
                status="leased",
                started_at=now,
                external_side_effect=False,
            )
            session.add(attempt)
            await session.commit()
            await session.refresh(row)
            await session.refresh(attempt)
        return JobLease(
            job=self._job_view(row),
            attempt=self._attempt_view(attempt),
            lease_token=token,
        )

    async def start(self, project_id: str, job_id: str, lease_token: str) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await self._leased_row(session, project_id, job_id, lease_token)
            if row.status != "leased":
                raise AgentRigError(ErrorCode.CONFLICT, "job is not in leased state")
            run = await session.scalar(
                select(RunORM)
                .where(
                    RunORM.id == row.run_id,
                    RunORM.project_id == project_id,
                )
                .with_for_update()
            )
            if run is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "durable run not found")
            attempt = await self._attempt_row(session, row)
            if run.status in {
                RunStatus.COMPLETED.value,
                RunStatus.CANCELLED.value,
                RunStatus.INTERRUPTED.value,
                RunStatus.FAILED.value,
            }:
                row.status = "cancelled"
                row.cancel_requested_at = utc_now()
                attempt.status = "cancelled"
                attempt.finished_at = utc_now()
                self._clear_lease(row)
                await session.commit()
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "run became terminal before durable job start",
                )
            row.status = "running"
            attempt.status = "running"
            run.status = RunStatus.RUNNING.value
            if run.started_at is None:
                run.started_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def heartbeat(
        self,
        project_id: str,
        job_id: str,
        lease_token: str,
        *,
        lease_seconds: int | None = None,
    ) -> ExecutionJobView:
        now = utc_now()
        async with self._database.session() as session:
            row = await self._leased_row(session, project_id, job_id, lease_token)
            if row.status not in {"leased", "running"}:
                raise AgentRigError(ErrorCode.CONFLICT, "job lease is no longer active")
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(
                seconds=lease_seconds or self._config.job_lease_seconds
            )
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def mark_external_side_effect(
        self, project_id: str, job_id: str, lease_token: str
    ) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await self._leased_row(session, project_id, job_id, lease_token)
            row.external_side_effect = True
            attempt = await self._attempt_row(session, row)
            attempt.external_side_effect = True
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def mark_external_side_effect_by_attempt(self, attempt_id: str) -> None:
        """Persist the no-retry fence before a durable Real Tool call starts."""

        async with self._database.session() as session:
            job_id = await session.scalar(
                select(ExecutionAttemptORM.job_id).where(ExecutionAttemptORM.id == attempt_id)
            )
            if job_id is None:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "durable execution attempt no longer exists",
                )
            row = await session.scalar(
                select(ExecutionJobORM).where(ExecutionJobORM.id == job_id).with_for_update()
            )
            if row is None:
                raise AgentRigError(ErrorCode.CONFLICT, "durable execution job is missing")
            attempt = await session.scalar(
                select(ExecutionAttemptORM)
                .where(ExecutionAttemptORM.id == attempt_id)
                .with_for_update()
            )
            if attempt is None:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "durable execution attempt no longer exists",
                )
            attempt.external_side_effect = True
            row.external_side_effect = True
            # A stale attempt that reaches this point after its lease was reaped
            # must fence any newer retry before the external request is sent.
            if row.status in {"queued", "leased", "running"} and (
                row.attempt != attempt.attempt
                or row.status == "queued"
                or attempt.status not in {"leased", "running"}
            ):
                row.status = "dead"
                row.last_error_code = "stale_attempt_external_side_effect"
                case_run = await session.get(CaseRunORM, row.case_run_id)
                if case_run is not None:
                    case_run.status = CaseRunStatus.FAILED.value
                    case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                    case_run.error_code = row.last_error_code
                    case_run.finished_at = utc_now()
                self._clear_lease(row)
                await session.commit()
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "stale durable attempt was fenced before external execution",
                )
            if row.status not in {"leased", "running"}:
                await session.commit()
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "durable attempt is not active for external execution",
                )
            await session.commit()

    async def complete(self, project_id: str, job_id: str, lease_token: str) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await self._leased_row(session, project_id, job_id, lease_token)
            if row.status not in {"leased", "running"}:
                raise AgentRigError(ErrorCode.CONFLICT, "job lease is no longer active")
            row.status = "completed"
            attempt = await self._attempt_row(session, row)
            attempt.status = "completed"
            attempt.finished_at = utc_now()
            self._clear_lease(row)
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def fail(
        self,
        project_id: str,
        job_id: str,
        lease_token: str,
        *,
        error_code: str,
        external_side_effect: bool = False,
    ) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await self._leased_row(session, project_id, job_id, lease_token)
            attempt = await self._attempt_row(session, row)
            row.last_error_code = error_code
            row.external_side_effect = row.external_side_effect or external_side_effect
            attempt.external_side_effect = attempt.external_side_effect or external_side_effect
            attempt.status = "failed"
            attempt.error_code = error_code
            attempt.finished_at = utc_now()
            case_run = await session.get(CaseRunORM, row.case_run_id)
            if row.external_side_effect or row.attempt >= row.max_attempts:
                row.status = "dead"
                if case_run is not None:
                    case_run.status = CaseRunStatus.FAILED.value
                    case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                    case_run.error_code = error_code
                    case_run.finished_at = utc_now()
            else:
                row.status = "queued"
                row.available_at = utc_now() + self._retry_delay(row.attempt)
                if case_run is not None:
                    case_run.status = CaseRunStatus.QUEUED.value
                    case_run.evaluation_state = EvaluationOutcome.AWAITING_VERDICT.value
                    case_run.error_code = None
                    case_run.error_message = None
                    case_run.finished_at = None
            self._clear_lease(row)
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def cancel(self, project_id: str, job_id: str) -> ExecutionJobView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(ExecutionJobORM)
                .where(
                    ExecutionJobORM.id == job_id,
                    ExecutionJobORM.project_id == project_id,
                )
                .with_for_update()
            )
            if row is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "execution job not found")
            if row.status in {"completed", "dead", "cancelled"}:
                return self._job_view(row)
            row.cancel_requested_at = utc_now()
            row.status = "cancelled"
            if row.attempt:
                attempt = await self._attempt_row(session, row)
                attempt.status = "cancelled"
                attempt.finished_at = utc_now()
            self._clear_lease(row)
            case_run = await session.get(CaseRunORM, row.case_run_id)
            if case_run is not None and case_run.status in {"queued", "running"}:
                case_run.status = CaseRunStatus.CANCELLED.value
                case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                case_run.error_code = "cancelled"
                case_run.finished_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return self._job_view(row)

    async def cancel_run(self, project_id: str, run_id: str) -> int:
        """Atomically cancel every non-terminal job and CaseRun in one Run."""

        now = utc_now()
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(ExecutionJobORM)
                    .where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.run_id == run_id,
                    )
                    .with_for_update()
                )
            )
            run = await session.scalar(
                select(RunORM)
                .where(
                    RunORM.project_id == project_id,
                    RunORM.id == run_id,
                )
                .with_for_update()
            )
            if run is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "durable run not found")
            if run.status in {
                RunStatus.COMPLETED.value,
                RunStatus.CANCELLED.value,
                RunStatus.INTERRUPTED.value,
                RunStatus.FAILED.value,
            }:
                return 0
            changed = 0
            for row in rows:
                if row.status in {"completed", "dead", "cancelled"}:
                    continue
                row.cancel_requested_at = now
                row.status = "cancelled"
                if row.attempt:
                    attempt = await self._attempt_row(session, row)
                    attempt.status = "cancelled"
                    attempt.finished_at = now
                self._clear_lease(row)
                changed += 1
            case_runs = list(
                await session.scalars(
                    select(CaseRunORM).where(
                        CaseRunORM.project_id == project_id,
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.status.in_(["queued", "running"]),
                    )
                )
            )
            for case_run in case_runs:
                case_run.status = CaseRunStatus.CANCELLED.value
                case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                case_run.error_code = "cancelled"
                case_run.finished_at = now
            await session.commit()
            return changed

    async def reconcile_case_runs(self, project_id: str, run_id: str) -> None:
        """Make durable Job terminal/retry state authoritative after late workers."""

        now = utc_now()
        async with self._database.session() as session:
            jobs = list(
                await session.scalars(
                    select(ExecutionJobORM)
                    .where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.run_id == run_id,
                    )
                    .with_for_update()
                )
            )
            if not jobs:
                return
            case_runs = list(
                await session.scalars(
                    select(CaseRunORM).where(
                        CaseRunORM.project_id == project_id,
                        CaseRunORM.run_id == run_id,
                    )
                )
            )
            case_by_id = {row.id: row for row in case_runs}
            for job in jobs:
                case_run = case_by_id.get(job.case_run_id)
                if case_run is None:
                    continue
                if job.status == "cancelled":
                    case_run.status = CaseRunStatus.CANCELLED.value
                    case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                    case_run.error_code = "cancelled"
                    case_run.finished_at = case_run.finished_at or now
                elif job.status in {"dead", "failed"}:
                    case_run.status = CaseRunStatus.FAILED.value
                    case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                    case_run.error_code = job.last_error_code or "durable_job_dead"
                    case_run.finished_at = case_run.finished_at or now
                elif job.status == "queued":
                    case_run.status = CaseRunStatus.QUEUED.value
                    case_run.evaluation_state = EvaluationOutcome.AWAITING_VERDICT.value
                    case_run.error_code = None
                    case_run.error_message = None
                    case_run.finished_at = None
            await session.commit()

    async def reap_expired(self, *, limit: int = 100) -> ReaperResult:
        now = utc_now()
        async with self._database.session() as session:
            query = (
                select(ExecutionJobORM)
                .where(
                    ExecutionJobORM.status.in_(["leased", "running"]),
                    ExecutionJobORM.lease_expires_at <= now,
                )
                .order_by(ExecutionJobORM.lease_expires_at)
                .limit(max(1, min(limit, 1_000)))
            )
            if self.backend == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = list(await session.scalars(query))
            requeued = dead = side_effect_dead = 0
            for row in rows:
                attempt = await self._attempt_row(session, row)
                attempt.status = "interrupted"
                attempt.error_code = "lease_expired"
                attempt.finished_at = now
                case_run = await session.get(CaseRunORM, row.case_run_id)
                if row.external_side_effect or attempt.external_side_effect:
                    row.status = "dead"
                    row.last_error_code = "lease_expired_after_external_side_effect"
                    dead += 1
                    side_effect_dead += 1
                elif row.attempt >= row.max_attempts:
                    row.status = "dead"
                    row.last_error_code = "lease_retry_exhausted"
                    dead += 1
                else:
                    row.status = "queued"
                    row.available_at = now + self._retry_delay(row.attempt)
                    row.last_error_code = "lease_expired"
                    requeued += 1
                if case_run is not None:
                    if row.status == "dead":
                        case_run.status = CaseRunStatus.FAILED.value
                        case_run.evaluation_state = EvaluationOutcome.INCONCLUSIVE.value
                        case_run.error_code = row.last_error_code
                        case_run.finished_at = now
                    else:
                        case_run.status = CaseRunStatus.QUEUED.value
                        case_run.evaluation_state = EvaluationOutcome.AWAITING_VERDICT.value
                        case_run.error_code = None
                        case_run.error_message = None
                        case_run.finished_at = None
                self._clear_lease(row)
            await session.commit()
        return ReaperResult(
            inspected=len(rows),
            requeued=requeued,
            dead=dead,
            side_effect_dead=side_effect_dead,
        )

    async def list_attempts(self, project_id: str, job_id: str) -> list[ExecutionAttemptView]:
        await self.get(project_id, job_id)
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(ExecutionAttemptORM)
                    .where(
                        ExecutionAttemptORM.project_id == project_id,
                        ExecutionAttemptORM.job_id == job_id,
                    )
                    .order_by(ExecutionAttemptORM.attempt)
                )
            )
        return [self._attempt_view(row) for row in rows]

    async def _leased_row(
        self, session: Any, project_id: str, job_id: str, lease_token: str
    ) -> ExecutionJobORM:
        row = await session.scalar(
            select(ExecutionJobORM)
            .where(
                ExecutionJobORM.id == job_id,
                ExecutionJobORM.project_id == project_id,
            )
            .with_for_update()
        )
        if (
            row is None
            or row.lease_token_hash is None
            or not hmac.compare_digest(row.lease_token_hash, self._token_hash(lease_token))
        ):
            raise AgentRigError(ErrorCode.CONFLICT, "invalid or superseded job lease")
        if row.lease_expires_at is None or self._expired(row.lease_expires_at, utc_now()):
            raise AgentRigError(ErrorCode.CONFLICT, "job lease expired")
        return cast(ExecutionJobORM, row)

    @staticmethod
    async def _attempt_row(session: Any, row: ExecutionJobORM) -> ExecutionAttemptORM:
        attempt = await session.scalar(
            select(ExecutionAttemptORM)
            .where(
                ExecutionAttemptORM.job_id == row.id,
                ExecutionAttemptORM.attempt == row.attempt,
            )
            .with_for_update()
        )
        if attempt is None:
            raise AgentRigError(ErrorCode.CONFLICT, "execution attempt not found")
        return cast(ExecutionAttemptORM, attempt)

    @staticmethod
    def _clear_lease(row: ExecutionJobORM) -> None:
        row.lease_owner = None
        row.lease_token_hash = None
        row.lease_expires_at = None
        row.heartbeat_at = None

    @staticmethod
    def _retry_delay(attempt: int) -> timedelta:
        return timedelta(seconds=min(60, 2 ** max(0, attempt - 1)))

    @staticmethod
    def _expired(value: datetime, now: datetime) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value <= now

    @staticmethod
    def _token_hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _job_view(row: ExecutionJobORM) -> ExecutionJobView:
        return ExecutionJobView.model_validate(row, from_attributes=True)

    @staticmethod
    def _attempt_view(row: ExecutionAttemptORM) -> ExecutionAttemptView:
        return ExecutionAttemptView.model_validate(row, from_attributes=True)

    @staticmethod
    def _worker_view(row: WorkerRegistrationORM) -> WorkerRegistrationView:
        return WorkerRegistrationView(
            worker_id=row.id,
            backend=cast(Any, row.backend),
            started_at=row.started_at,
            heartbeat_at=row.heartbeat_at,
            expires_at=row.expires_at,
        )


class DurableWorker:
    def __init__(
        self,
        jobs: DurableJobService,
        executor: CaseExecutor,
        runs: RunRepository,
        config: ExecutionConfig,
    ) -> None:
        self._jobs = jobs
        self._executor = executor
        self._runs = runs
        self._config = config
        self._completion_listeners: list[RunCompletionListener] = []

    def add_completion_listener(self, listener: RunCompletionListener) -> None:
        self._completion_listeners.append(listener)

    async def finalize_run(self, project_id: str, run_id: str) -> None:
        await self._jobs.reconcile_case_runs(project_id, run_id)
        await self._runs.refresh_run_counts(run_id)
        await self._finalize_run(project_id, run_id)

    async def cancel_run(self, project_id: str, run_id: str) -> None:
        await self._jobs.cancel_run(project_id, run_id)
        await self._runs.refresh_run_counts(run_id)
        await self._finalize_run(
            project_id,
            run_id,
            empty_status=RunStatus.CANCELLED,
        )

    async def recover_expired(self, *, limit: int = 100) -> ReaperResult:
        await self._recover_undispatched_runs(limit=max(100, limit))
        result = await self._jobs.reap_expired(limit=limit)
        await self._finalize_ready_runs(limit=max(100, limit))
        return result

    async def run_once(self, worker_id: str) -> bool:
        lease = await self._jobs.claim(worker_id)
        if lease is None:
            return False
        project_id = lease.job.project_id
        try:
            await self._jobs.start(project_id, lease.job.id, lease.lease_token)
        except AgentRigError:
            await self.finalize_run(project_id, lease.job.run_id)
            return True
        cancel_event = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._maintain_lease(lease, cancel_event),
            name=f"agentrig-heartbeat:{lease.job.id}",
        )
        try:
            with execution_attempt(lease.attempt.id):
                await self._executor.execute(lease.job.case_run_id, cancel_event)
            detail = await self._runs.get_case_run(lease.job.case_run_id)
            if detail is not None and detail.status is CaseRunStatus.COMPLETED:
                await self._jobs.complete(project_id, lease.job.id, lease.lease_token)
            elif not cancel_event.is_set():
                await self._jobs.fail(
                    project_id,
                    lease.job.id,
                    lease.lease_token,
                    error_code=(detail.error_code if detail else "case_run_missing")
                    or "execution_failed",
                )
        except AgentRigError:
            # Lease fencing or cancellation means a newer owner is authoritative.
            cancel_event.set()
        except Exception:
            try:
                await self._jobs.fail(
                    project_id,
                    lease.job.id,
                    lease.lease_token,
                    error_code="worker_internal_error",
                )
            except AgentRigError:
                pass
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await self.finalize_run(project_id, lease.job.run_id)
        return True

    async def _maintain_lease(self, lease: JobLease, cancel_event: asyncio.Event) -> None:
        interval = max(1.0, self._config.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._jobs.heartbeat(
                    lease.job.project_id,
                    lease.job.id,
                    lease.lease_token,
                )
            except AgentRigError:
                cancel_event.set()
                return

    async def _recover_undispatched_runs(self, *, limit: int) -> None:
        async with self._jobs._database.session() as session:
            queued_runs = list(
                await session.scalars(
                    select(RunORM)
                    .outerjoin(
                        EvaluationPlanORM,
                        (EvaluationPlanORM.project_id == RunORM.project_id)
                        & (EvaluationPlanORM.run_id == RunORM.id),
                    )
                    .where(
                        RunORM.status == RunStatus.QUEUED.value,
                        or_(
                            RunORM.selection_snapshot["dispatch_intent"].as_string() == "immediate",
                            EvaluationPlanORM.status == "submitted",
                        ),
                    )
                    .order_by(RunORM.created_at, RunORM.id)
                    .limit(max(1, min(limit, 1_000)))
                )
            )
            recoverable: list[tuple[str, str, list[str]]] = []
            for run in queued_runs:
                case_run_ids = list(
                    await session.scalars(
                        select(CaseRunORM.id)
                        .where(
                            CaseRunORM.project_id == run.project_id,
                            CaseRunORM.run_id == run.id,
                            CaseRunORM.status == CaseRunStatus.QUEUED.value,
                        )
                        .order_by(CaseRunORM.id)
                    )
                )
                if case_run_ids:
                    recoverable.append((run.project_id, run.id, case_run_ids))
        for project_id, run_id, case_run_ids in recoverable:
            await self._jobs.enqueue_plan(project_id, run_id, case_run_ids)

    async def _finalize_ready_runs(self, *, limit: int) -> None:
        active_job = aliased(ExecutionJobORM)
        active_exists = exists(
            select(active_job.id).where(
                active_job.project_id == ExecutionJobORM.project_id,
                active_job.run_id == ExecutionJobORM.run_id,
                active_job.status.in_(["queued", "leased", "running"]),
            )
        )
        async with self._jobs._database.session() as session:
            ready = list(
                (
                    await session.execute(
                        select(
                            ExecutionJobORM.project_id,
                            ExecutionJobORM.run_id,
                        )
                        .join(
                            RunORM,
                            (RunORM.id == ExecutionJobORM.run_id)
                            & (RunORM.project_id == ExecutionJobORM.project_id),
                        )
                        .where(
                            RunORM.status.not_in(
                                [
                                    RunStatus.COMPLETED.value,
                                    RunStatus.CANCELLED.value,
                                    RunStatus.INTERRUPTED.value,
                                    RunStatus.FAILED.value,
                                ]
                            ),
                            ~active_exists,
                        )
                        .distinct()
                        .limit(max(1, min(limit, 1_000)))
                    )
                ).all()
            )
        for project_id, run_id in ready:
            await self.finalize_run(str(project_id), str(run_id))

    async def _finalize_run(
        self,
        project_id: str,
        run_id: str,
        *,
        empty_status: RunStatus | None = None,
    ) -> None:
        terminal_statuses = {
            RunStatus.COMPLETED.value,
            RunStatus.CANCELLED.value,
            RunStatus.INTERRUPTED.value,
            RunStatus.FAILED.value,
        }
        run_view: RunView | None = None
        async with self._jobs._database.session() as session:
            statuses = list(
                await session.scalars(
                    select(ExecutionJobORM.status).where(
                        ExecutionJobORM.project_id == project_id,
                        ExecutionJobORM.run_id == run_id,
                    )
                )
            )
            if not statuses and empty_status is None:
                return
            if any(status in {"queued", "leased", "running"} for status in statuses):
                return

            # Competing PostgreSQL workers can finish the last jobs concurrently.
            # Locking the Run makes the terminal transition, and therefore its
            # completion notification, a single-winner operation. SQLite permits
            # only one registered worker, so its ignored FOR UPDATE is sufficient.
            run = await session.scalar(
                select(RunORM)
                .where(
                    RunORM.project_id == project_id,
                    RunORM.id == run_id,
                )
                .with_for_update()
            )
            if run is None or run.status in terminal_statuses:
                return

            if not statuses:
                assert empty_status is not None
                run.status = empty_status.value
                run.error_code = None
                run.error_message = None
            elif any(status in {"dead", "failed"} for status in statuses):
                run.status = RunStatus.FAILED.value
                run.error_code = "durable_job_dead"
                run.error_message = "one or more durable execution jobs exhausted recovery"
            elif any(status == "cancelled" for status in statuses):
                run.status = RunStatus.CANCELLED.value
                run.error_code = None
                run.error_message = None
            else:
                run.status = RunStatus.COMPLETED.value
                run.error_code = None
                run.error_message = None
            run.finished_at = utc_now()
            await session.flush()
            run_view = RunView.model_validate(run, from_attributes=True)
            await session.commit()

        assert run_view is not None
        for listener in self._completion_listeners:
            try:
                await listener(run_view)
            except Exception:
                # Completion hooks are intentionally best effort and must never
                # roll a committed Run back out of its terminal state.
                logger.exception("run completion listener failed for %s", run_id)
