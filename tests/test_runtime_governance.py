from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import cast

import httpx
import pytest

from agentrig.config import ExecutionConfig
from agentrig.errors import AgentRigError
from agentrig.failures import (
    FailureLinksUpdate,
    FailureMonitorCreate,
    FailurePatternCreate,
    FailurePatternTransition,
    FailureSignalCreate,
    MembershipReview,
)
from agentrig.failures.service import FailureGovernanceService
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.orm import (
    CaseRunORM,
    ExecutionJobORM,
    RunORM,
    utc_now,
)
from agentrig.infrastructure.database.orm import (
    TestCaseORM as CaseORM,
)
from agentrig.infrastructure.database.repositories.runs import SqlRunRepository
from agentrig.infrastructure.secrets import SecretResolver
from agentrig.jobs import DurableJobService, DurableWorker, ExecutionJobCreate
from agentrig.projects import ProjectService
from agentrig.reviews import (
    AlignmentPrediction,
    AlignmentRunCreate,
    AnnotationCreate,
    EvaluatorActivate,
    EvaluatorVersionCreate,
    GoldLabelResolve,
    ReviewItemCreate,
)
from agentrig.reviews.service import ReviewAlignmentService
from agentrig.runs.event_recorder import EventRecorder, execution_attempt
from agentrig.runs.executor import CaseExecutor
from agentrig.runs.models import RunStatus
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import RunView

pytestmark = pytest.mark.asyncio


async def _database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    await ProjectService(database).ensure_default()
    now = utc_now()
    async with database.session() as session:
        session.add(
            CaseORM(
                id="case_verified",
                project_id="default",
                name="Verified regression case",
                description="",
                review_status="approved",
                supported_versions=[],
                primary_evaluator="rule",
                initial_state={},
                case_assertions=[],
            )
        )
        session.add(
            RunORM(
                id="run_verified",
                project_id="default",
                status="completed",
                selection_snapshot={},
                resolved_case_ids=["case_verified"],
                profile_snapshot={},
                target_snapshots=[],
                total_count=1,
                completed_count=1,
                failed_count=0,
                skipped_count=0,
                cancelled_count=0,
                started_at=now,
                finished_at=now,
            )
        )
        await session.flush()
        session.add(
            CaseRunORM(
                id="case_run_verified",
                project_id="default",
                run_id="run_verified",
                case_id="case_verified",
                case_snapshot={"id": "case_verified"},
                target_snapshot={"id": "target", "driver_type": "test"},
                profile_snapshot={},
                capability_snapshot={"snapshot_hash": "sha256:verified"},
                repeat_index=0,
                status="completed",
                primary_evaluator="rule",
                evaluation_state="pass",
                started_at=now,
                finished_at=now,
                summary={},
            )
        )
        await session.commit()
    return database


async def test_review_alignment_is_append_only_and_requires_independent_approval() -> None:
    database = await _database()
    service = ReviewAlignmentService(database)
    try:
        review = await service.create_review_item(
            "default",
            ReviewItemCreate(
                subject_kind="case_run",
                subject_id="case_run_verified",
                required_reviews=2,
                cohort="critical-safety",
                created_reason="rule and Judge disagree",
                created_by="triage",
            ),
        )
        first = await service.add_annotation(
            "default",
            review.id,
            AnnotationCreate(
                reviewer_id="reviewer-a",
                label="pass",
                evidence_refs=["case_run:case_run_verified"],
                rationale_summary="blocking requirement is evidenced",
                confidence="high",
            ),
        )
        replacement = await service.add_annotation(
            "default",
            review.id,
            AnnotationCreate(
                reviewer_id="reviewer-a",
                label="pass",
                evidence_refs=["case_run:case_run_verified"],
                rationale_summary="same verdict with a clearer public summary",
                confidence="high",
                supersedes=first.id,
            ),
        )
        await service.add_annotation(
            "default",
            review.id,
            AnnotationCreate(
                reviewer_id="reviewer-b",
                label="pass",
                evidence_refs=["case_run:case_run_verified"],
                rationale_summary="independent replay agrees",
                confidence="high",
            ),
        )
        annotations = await service.list_annotations("default", review.id)
        assert [item.revision for item in annotations] == [1, 2, 3]
        assert replacement.supersedes == first.id

        gold = await service.resolve(
            "default",
            review.id,
            GoldLabelResolve(
                adjudicator_id="adjudicator",
                role="adjudicator",
                label="pass",
                rationale_summary="two independent current annotations agree",
            ),
        )
        assert gold.source_annotation_ids == [replacement.id, annotations[2].id]
        assert gold.resolution_method == "consensus"

        ordinary_review = await service.create_review_item(
            "default",
            ReviewItemCreate(
                subject_kind="case_run",
                subject_id="case_run_verified",
                required_reviews=1,
                cohort="ordinary-regression",
                created_reason="ordinary quality calibration",
                created_by="triage",
            ),
        )
        ordinary_annotation = await service.add_annotation(
            "default",
            ordinary_review.id,
            AnnotationCreate(
                reviewer_id="reviewer-c",
                label="pass",
                evidence_refs=["case_run:case_run_verified"],
                rationale_summary="ordinary behavior matches the public requirement",
                confidence="high",
            ),
        )
        ordinary_gold = await service.resolve(
            "default",
            ordinary_review.id,
            GoldLabelResolve(
                adjudicator_id="adjudicator",
                role="adjudicator",
                label="pass",
                rationale_summary="single-review ordinary cohort policy is satisfied",
            ),
        )
        assert ordinary_gold.source_annotation_ids == [ordinary_annotation.id]

        evaluator = await service.create_evaluator_version(
            "default",
            EvaluatorVersionCreate(
                evaluator_id="release-judge",
                evaluator_kind="evidence_judge",
                name="Release Judge",
                semantic_version="1.1.0",
                code_revision="git:abc123",
                prompt_version="judge-v2",
                prompt_hash="sha256:prompt",
                model_id="model-a",
                model_parameters={"temperature": 0},
                output_schema_hash="sha256:schema",
                created_by="judge-author",
            ),
        )
        alignment = await service.run_alignment(
            "default",
            evaluator.id,
            AlignmentRunCreate(
                gold_label_ids=[gold.id, ordinary_gold.id],
                predictions=[
                    AlignmentPrediction(
                        gold_label_id=gold.id,
                        predicted_label="pass",
                        cohorts={"risk": "critical", "runtime": "agentscope-2.0"},
                    ),
                    AlignmentPrediction(
                        gold_label_id=ordinary_gold.id,
                        predicted_label="pass",
                        cohorts={
                            "risk": "ordinary",
                            "runtime": "reference",
                            "source": "regression-suite",
                        },
                    ),
                ],
            ),
        )
        assert alignment.metrics.coverage == 1
        assert alignment.metrics.agreement == 1
        assert alignment.cohort_metrics["risk:critical"].false_pass_rate == 0
        assert alignment.cohort_metrics["risk:ordinary"].agreement == 1
        assert alignment.cohort_metrics["source:regression-suite"].coverage == 1
        with pytest.raises(AgentRigError):
            await service.activate_evaluator(
                "default",
                evaluator.id,
                EvaluatorActivate(
                    alignment_run_id=alignment.id,
                    approved_by="judge-author",
                ),
            )
        active = await service.activate_evaluator(
            "default",
            evaluator.id,
            EvaluatorActivate(
                alignment_run_id=alignment.id,
                approved_by="evaluator-admin",
            ),
        )
        assert active.status == "active"
        assert active.content_hash == evaluator.content_hash
    finally:
        await database.dispose()


async def test_failure_pattern_requires_verified_fix_and_detects_critical_recurrence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = await _database()
    monkeypatch.setenv("AGENTRIG_FAILURE_WEBHOOK_SECRET", "test-webhook-secret")
    requests: list[httpx.Request] = []
    fail_delivery = False

    def webhook(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503 if fail_delivery else 200)

    service = FailureGovernanceService(
        database,
        secrets=SecretResolver(),
        webhook_transport=httpx.MockTransport(webhook),
    )
    try:
        signal = await service.ingest_signal(
            "default",
            FailureSignalCreate(
                source_kind="manual",
                source_id="incident-1",
                signal_type="permission-bypass",
                category="runtime-safety",
                severity="critical",
                summary="permission denial was bypassed",
                detector_version="rule-v1",
                environment="production",
                attributes={"invariant": "permission-denial"},
            ),
        )
        duplicate = await service.ingest_signal(
            "default",
            FailureSignalCreate(
                source_kind="manual",
                source_id="incident-1",
                signal_type="permission-bypass",
                category="runtime-safety",
                severity="critical",
                summary="permission denial was bypassed",
                detector_version="rule-v1",
                environment="production",
                attributes={"invariant": "permission-denial"},
            ),
        )
        assert duplicate.id == signal.id
        pattern = await service.create_pattern(
            "default",
            FailurePatternCreate(
                title="Permission denial bypass",
                severity="critical",
                owner="runtime-owner",
                signal_ids=[signal.id],
                created_by="triage",
            ),
        )
        await service.review_memberships(
            "default",
            pattern.id,
            MembershipReview(
                reviewer_id="reviewer",
                decisions=[
                    {
                        "signal_id": signal.id,
                        "decision": "confirmed",
                        "explanation": "exact invariant match",
                    }
                ],
            ),
        )
        pattern = await service.transition(
            "default",
            pattern.id,
            FailurePatternTransition(
                target_status="new",
                actor="reviewer",
                reason="confirmed product issue",
            ),
        )
        pattern = await service.transition(
            "default",
            pattern.id,
            FailurePatternTransition(
                target_status="ongoing",
                actor="runtime-owner",
                reason="fix in progress",
            ),
        )
        with pytest.raises(AgentRigError):
            await service.transition(
                "default",
                pattern.id,
                FailurePatternTransition(
                    target_status="resolved",
                    actor="runtime-owner",
                    reason="code merged without evidence",
                    resolved_by_run_id="run_verified",
                ),
            )
        await service.update_links(
            "default",
            pattern.id,
            FailureLinksUpdate(
                actor="runtime-owner",
                linked_case_ids=["case_verified"],
                linked_suite_versions=["suite-runtime-safety@1"],
                linked_release_gate_ids=["gate-1"],
                release={"environment": "production", "version": "2.4.0"},
            ),
        )
        pattern = await service.transition(
            "default",
            pattern.id,
            FailurePatternTransition(
                target_status="resolved",
                actor="runtime-owner",
                reason="approved regression suite passed",
                resolved_by_run_id="run_verified",
            ),
        )
        assert pattern.status == "resolved"
        monitor = await service.create_monitor(
            "default",
            pattern.id,
            FailureMonitorCreate.model_validate(
                {
                    "environment": "production",
                    "shadow_mode": False,
                    "webhook": {
                        "url": "https://webhook.example.test/failure",
                        "secret_ref": "env:AGENTRIG_FAILURE_WEBHOOK_SECRET",
                        "max_attempts": 2,
                    },
                }
            ),
        )
        recurrence = await service.ingest_signal(
            "default",
            FailureSignalCreate(
                source_kind="manual",
                source_id="incident-2",
                signal_type="permission-bypass",
                category="runtime-safety",
                severity="critical",
                summary="same invariant returned after release",
                detector_version="rule-v1",
                environment="production",
                attributes={"invariant": "permission-denial"},
            ),
        )
        pattern = await service.get_pattern("default", pattern.id)
        monitors = await service.list_monitors("default", pattern.id)
        assert pattern.status == "regressed"
        assert monitors[0].id == monitor.id
        assert monitors[0].cursor == recurrence.id
        assert monitors[0].recurrence_count == 1
        assert any(
            event.event_type == "regressed"
            for event in await service.timeline("default", pattern.id)
        )

        delivered = await service.dispatch_webhook(
            "default",
            monitor.id,
            idempotency_key="pattern-regressed-1",
        )
        repeated = await service.dispatch_webhook(
            "default",
            monitor.id,
            idempotency_key="pattern-regressed-1",
        )
        assert delivered.status == repeated.status == "delivered"
        assert delivered.id == repeated.id
        assert len(requests) == 1
        body = requests[0].content
        payload = json.loads(body)
        assert set(payload) == {
            "schema_version",
            "pattern_id",
            "title",
            "severity",
            "status",
            "release",
            "recurrence_count",
            "url_path",
        }
        assert "permission denial was bypassed" not in body.decode().casefold()
        expected_signature = hmac.new(
            b"test-webhook-secret",
            body,
            hashlib.sha256,
        ).hexdigest()
        assert requests[0].headers["x-agentrig-signature"] == (f"sha256={expected_signature}")

        fail_delivery = True
        failed = await service.dispatch_webhook(
            "default",
            monitor.id,
            idempotency_key="pattern-regressed-2",
        )
        assert failed.status == "failed"
        assert (await service.get_pattern("default", pattern.id)).status == "regressed"
    finally:
        await database.dispose()


async def test_durable_job_fences_late_workers_and_never_retries_side_effects() -> None:
    database = await _database()
    async with database.session() as session:
        run = await session.get(RunORM, "run_verified")
        case_run = await session.get(CaseRunORM, "case_run_verified")
        assert run is not None and case_run is not None
        run.status = RunStatus.QUEUED.value
        run.finished_at = None
        case_run.status = "queued"
        case_run.evaluation_state = "awaiting_verdict"
        case_run.finished_at = None
        await session.commit()
    service = DurableJobService(
        database,
        ExecutionConfig(
            durable_scheduler_enabled=True,
            job_lease_seconds=10,
            worker_registration_ttl_seconds=30,
        ),
    )
    try:
        await service.register_worker("worker-a")
        with pytest.raises(AgentRigError):
            await service.register_worker("worker-b")
        job = await service.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_verified",
                idempotency_key="durable-case-run",
            ),
        )
        assert (
            await service.enqueue(
                "default",
                ExecutionJobCreate(
                    run_id="run_verified",
                    case_run_id="case_run_verified",
                    idempotency_key="durable-case-run",
                ),
            )
        ).id == job.id
        with pytest.raises(AgentRigError):
            await service.enqueue(
                "default",
                ExecutionJobCreate(
                    run_id="run_verified",
                    case_run_id="case_run_verified",
                    idempotency_key="different-key-same-case-run",
                ),
            )
        lease = await service.claim("worker-a")
        assert lease is not None
        assert "lease_token_hash" not in lease.model_dump(mode="json")
        await service.start("default", job.id, lease.lease_token)
        with pytest.raises(AgentRigError):
            await service.heartbeat("default", job.id, "wrong-token")
        recorder = EventRecorder(
            SqlRunRepository(database),
            Redactor(),
            external_side_effect_listener=(service.mark_external_side_effect_by_attempt),
        )
        with execution_attempt(lease.attempt.id):
            await recorder.mark_external_side_effect()
        async with database.session() as session:
            row = await session.get(ExecutionJobORM, job.id)
            assert row is not None
            row.lease_expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        reaped = await service.reap_expired()
        assert reaped.side_effect_dead == 1
        assert (await service.get("default", job.id)).status == "dead"
        with pytest.raises(AgentRigError):
            await service.complete("default", job.id, lease.lease_token)
        attempts = await service.list_attempts("default", job.id)
        assert attempts[0].status == "interrupted"
        assert attempts[0].external_side_effect is True

        async with database.session() as session:
            session.add(
                CaseRunORM(
                    id="case_run_stale",
                    project_id="default",
                    run_id="run_verified",
                    case_id="case_verified",
                    case_snapshot={"id": "case_verified"},
                    target_snapshot={"id": "target", "driver_type": "test"},
                    profile_snapshot={},
                    repeat_index=1,
                    status="queued",
                    primary_evaluator="rule",
                    evaluation_state="awaiting_verdict",
                    summary={},
                )
            )
            await session.commit()
        stale_job = await service.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_stale",
                idempotency_key="stale-side-effect-race",
            ),
        )
        stale_lease = await service.claim("worker-a")
        assert stale_lease is not None
        async with database.session() as session:
            row = await session.get(ExecutionJobORM, stale_job.id)
            assert row is not None
            row.lease_expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        assert (await service.reap_expired()).requeued == 1
        async with database.session() as session:
            row = await session.get(ExecutionJobORM, stale_job.id)
            assert row is not None
            row.available_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        replacement = await service.claim("worker-a")
        assert replacement is not None
        assert replacement.attempt.attempt == 2
        with pytest.raises(AgentRigError):
            await service.mark_external_side_effect_by_attempt(stale_lease.attempt.id)
        assert (await service.get("default", stale_job.id)).status == "dead"
        with pytest.raises(AgentRigError):
            await service.complete(
                "default",
                stale_job.id,
                replacement.lease_token,
            )
    finally:
        await database.dispose()


@pytest.mark.parametrize(
    ("job_status", "expected_status", "expected_error"),
    [
        ("completed", RunStatus.COMPLETED, None),
        ("cancelled", RunStatus.CANCELLED, None),
        ("dead", RunStatus.FAILED, "durable_job_dead"),
    ],
)
async def test_durable_worker_finalizes_and_notifies_exactly_once(
    job_status: str,
    expected_status: RunStatus,
    expected_error: str | None,
) -> None:
    database = await _database()
    config = ExecutionConfig(durable_scheduler_enabled=True)
    jobs = DurableJobService(database, config)
    repository = SqlRunRepository(database)
    worker = DurableWorker(
        jobs,
        cast(CaseExecutor, object()),
        repository,
        config,
    )
    notifications: list[RunView] = []

    async def broken_listener(_run: RunView) -> None:
        raise RuntimeError("listener unavailable")

    async def record_listener(run: RunView) -> None:
        notifications.append(run)

    worker.add_completion_listener(broken_listener)
    worker.add_completion_listener(record_listener)
    try:
        async with database.session() as session:
            run = await session.get(RunORM, "run_verified")
            case_run = await session.get(CaseRunORM, "case_run_verified")
            assert run is not None and case_run is not None
            run.status = RunStatus.QUEUED.value
            run.finished_at = None
            case_run.status = "queued"
            case_run.evaluation_state = "awaiting_verdict"
            case_run.finished_at = None
            await session.commit()
        job = await jobs.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_verified",
                idempotency_key=f"terminal-{job_status}",
            ),
        )
        async with database.session() as session:
            run = await session.get(RunORM, "run_verified")
            row = await session.get(ExecutionJobORM, job.id)
            assert run is not None and row is not None
            run.status = RunStatus.RUNNING.value
            run.finished_at = None
            row.status = job_status
            await session.commit()

        await worker._finalize_run("default", "run_verified")
        await worker._finalize_run("default", "run_verified")

        finalized = await repository.get_run("run_verified")
        assert finalized is not None
        assert finalized.status is expected_status
        assert finalized.error_code == expected_error
        assert finalized.finished_at is not None
        assert len(notifications) == 1
        assert notifications[0].status is expected_status
    finally:
        await database.dispose()


async def test_durable_run_cancel_wins_over_partial_completion() -> None:
    database = await _database()
    config = ExecutionConfig(durable_scheduler_enabled=True)
    jobs = DurableJobService(database, config)
    repository = SqlRunRepository(database)
    worker = DurableWorker(
        jobs,
        cast(CaseExecutor, object()),
        repository,
        config,
    )
    notifications: list[RunView] = []

    async def record_listener(run: RunView) -> None:
        notifications.append(run)

    worker.add_completion_listener(record_listener)
    try:
        async with database.session() as session:
            run = await session.get(RunORM, "run_verified")
            first_case = await session.get(CaseRunORM, "case_run_verified")
            assert run is not None and first_case is not None
            run.status = RunStatus.RUNNING.value
            run.finished_at = None
            first_case.status = "queued"
            first_case.evaluation_state = "awaiting_verdict"
            first_case.finished_at = None
            session.add(
                CaseRunORM(
                    id="case_run_cancelled_remainder",
                    project_id="default",
                    run_id="run_verified",
                    case_id="case_verified",
                    case_snapshot={"id": "case_verified"},
                    target_snapshot={"id": "target", "driver_type": "test"},
                    profile_snapshot={},
                    repeat_index=1,
                    status="queued",
                    primary_evaluator="rule",
                    evaluation_state="awaiting_verdict",
                    summary={},
                )
            )
            await session.commit()
        first_job = await jobs.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_verified",
                idempotency_key="partially-completed",
            ),
        )
        second_job = await jobs.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_cancelled_remainder",
                idempotency_key="cancelled-remainder",
            ),
        )
        async with database.session() as session:
            first_job_row = await session.get(ExecutionJobORM, first_job.id)
            first_case = await session.get(CaseRunORM, "case_run_verified")
            assert first_job_row is not None and first_case is not None
            first_job_row.status = "completed"
            first_case.status = "completed"
            first_case.evaluation_state = "pass"
            first_case.finished_at = utc_now()
            await session.commit()

        await worker.cancel_run("default", "run_verified")

        finalized = await repository.get_run("run_verified")
        assert finalized is not None
        assert finalized.status is RunStatus.CANCELLED
        assert finalized.completed_count == 1
        assert finalized.cancelled_count == 1
        assert (await jobs.get("default", first_job.id)).status == "completed"
        assert (await jobs.get("default", second_job.id)).status == "cancelled"
        assert [item.status for item in notifications] == [RunStatus.CANCELLED]
    finally:
        await database.dispose()


async def test_durable_recovery_finalizes_exhausted_job() -> None:
    database = await _database()
    config = ExecutionConfig(
        durable_scheduler_enabled=True,
        job_lease_seconds=10,
        job_max_attempts=1,
    )
    jobs = DurableJobService(database, config)
    repository = SqlRunRepository(database)
    worker = DurableWorker(
        jobs,
        cast(CaseExecutor, object()),
        repository,
        config,
    )
    try:
        async with database.session() as session:
            run = await session.get(RunORM, "run_verified")
            case_run = await session.get(CaseRunORM, "case_run_verified")
            assert run is not None and case_run is not None
            run.status = RunStatus.QUEUED.value
            run.finished_at = None
            case_run.status = "queued"
            case_run.evaluation_state = "awaiting_verdict"
            case_run.finished_at = None
            await session.commit()
        await jobs.register_worker("recovery-worker")
        job = await jobs.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_verified",
                case_run_id="case_run_verified",
                idempotency_key="recovery-exhausted",
                max_attempts=1,
            ),
        )
        lease = await jobs.claim("recovery-worker")
        assert lease is not None
        await jobs.start("default", job.id, lease.lease_token)
        async with database.session() as session:
            row = await session.get(ExecutionJobORM, job.id)
            assert row is not None
            row.lease_expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()

        result = await worker.recover_expired()

        assert result.dead == 1
        finalized = await repository.get_run("run_verified")
        async with database.session() as session:
            case_run = await session.get(CaseRunORM, "case_run_verified")
        assert finalized is not None and case_run is not None
        assert finalized.status is RunStatus.FAILED
        assert finalized.error_code == "durable_job_dead"
        assert case_run.status == "failed"
        assert case_run.error_code == "lease_retry_exhausted"
    finally:
        await database.dispose()


@pytest.mark.parametrize(
    ("dispatch_intent", "expected_jobs"),
    [
        ("immediate", 1),
        ("evaluation_plan", 0),
    ],
)
async def test_durable_recovery_only_dispatches_committed_intent(
    dispatch_intent: str,
    expected_jobs: int,
) -> None:
    database = await _database()
    config = ExecutionConfig(durable_scheduler_enabled=True)
    jobs = DurableJobService(database, config)
    worker = DurableWorker(
        jobs,
        cast(CaseExecutor, object()),
        SqlRunRepository(database),
        config,
    )
    try:
        async with database.session() as session:
            run = await session.get(RunORM, "run_verified")
            case_run = await session.get(CaseRunORM, "case_run_verified")
            assert run is not None and case_run is not None
            run.status = RunStatus.QUEUED.value
            run.selection_snapshot = {"dispatch_intent": dispatch_intent}
            run.finished_at = None
            case_run.status = "queued"
            case_run.evaluation_state = "awaiting_verdict"
            case_run.finished_at = None
            await session.commit()

        await worker.recover_expired()

        page = await jobs.list_jobs("default", limit=10, offset=0)
        assert page.total == expected_jobs
        if expected_jobs:
            assert page.items[0].case_run_id == "case_run_verified"
            assert page.items[0].status == "queued"
    finally:
        await database.dispose()
