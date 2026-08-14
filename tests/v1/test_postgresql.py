"""可选 PostgreSQL Repository 集成测试。

只有显式提供名称中包含 ``test`` 的数据库 URL 才运行，避免误删普通数据库表。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from sqlalchemy import update
from sqlalchemy.engine import make_url

from agentrig.assistant import (
    AssistantMessageCreate,
    AssistantSessionCreate,
    ManagerDecisionProposal,
)
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.cases.service import CaseService
from agentrig.config import ExecutionConfig, ProductionEvidenceConfig, Settings
from agentrig.errors import AgentRigError
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.orm import (
    CaseRunORM,
    ExecutionJobORM,
    RunORM,
    utc_now,
)
from agentrig.infrastructure.database.orm import TestCaseORM as CaseORM
from agentrig.infrastructure.database.repositories import (
    SqlCaseRepository,
    SqlRunRepository,
)
from agentrig.jobs import DurableJobService, DurableWorker, ExecutionJobCreate
from agentrig.production import (
    IngestSourceCreate,
    ProductionEvidenceService,
    ProductionRetentionRequest,
)
from agentrig.projects import ProjectService
from agentrig.runs.executor import CaseExecutor
from agentrig.runs.models import RunStatus
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import RunView


async def test_postgresql_case_repository_round_trip() -> None:
    raw_url = os.environ.get("AGENTRIG_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("AGENTRIG_TEST_POSTGRES_URL is not configured")
    database_name = make_url(raw_url).database or ""
    if "test" not in database_name.lower():
        pytest.skip("PostgreSQL integration database name must contain 'test'")

    database = Database(raw_url)
    await database.drop_schema()
    await database.create_schema()
    try:
        service = CaseService(SqlCaseRepository(database))
        created = await service.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_postgresql",
                    "name": "PostgreSQL",
                    "tags": ["cap.search"],
                    "primary_evaluator": "external_controller",
                    "turns": [{"position": 1, "user_message": "hello"}],
                }
            )
        )
        loaded = await service.get(created.id)
        assert loaded.model_dump(mode="json") == created.model_dump(mode="json")
        assert (await service.list_cases()).total == 1
    finally:
        await database.drop_schema()
        await database.dispose()


async def test_postgresql_serializes_decisions_across_service_instances() -> None:
    raw_url = _postgres_test_url()
    database_a = Database(raw_url)
    database_b = Database(raw_url)
    await database_a.drop_schema()
    await database_a.create_schema()
    settings = Settings(database={"url": raw_url})
    service_a = ServiceContainer.build(settings, database=database_a)
    service_b = ServiceContainer.build(settings, database=database_b)
    try:
        session = await service_a.assistant.create_session(
            AssistantSessionCreate(title="concurrent decisions"),
            created_by="postgres-test",
        )
        message = await service_a.assistant.send_message(
            session.id,
            AssistantMessageCreate(
                client_message_id="postgres-message",
                content="record concurrent decisions",
            ),
            actor_id="postgres-test",
        )

        def proposal(index: int, key: str) -> ManagerDecisionProposal:
            return ManagerDecisionProposal(
                session_id=session.id,
                turn_id=message.turn_id,
                trigger="user_request",
                decision_kind="clarification",
                objective=f"record concurrent decision {index}",
                observation_summary={"known": ["the request event exists"]},
                options=[{"action_type": "no_action", "label": "record only"}],
                selected_action={"action_type": "no_action"},
                rationale_summary={"summary": "No mutation is required."},
                evidence_refs=[{"kind": "assistant_event", "resource_id": message.event_id}],
                idempotency_key=key,
            )

        records = await asyncio.gather(
            service_a.decisions.record(proposal(1, "postgres-decision-1")),
            service_b.decisions.record(proposal(2, "postgres-decision-2")),
            service_a.decisions.record(proposal(3, "postgres-shared")),
            service_b.decisions.record(proposal(3, "postgres-shared")),
        )
        assert records[2].id == records[3].id
        assert sorted({item.ordinal for item in records}) == [1, 2, 3]
        events = await service_a.assistant.list_events(session.id)
        assert len([item for item in events.items if item.decision_id]) == 3
    finally:
        await service_a.close()
        await service_b.close()
        cleanup = Database(raw_url)
        await cleanup.drop_schema()
        await cleanup.dispose()


async def test_postgresql_two_workers_use_skip_locked_and_lease_fencing() -> None:
    raw_url = _postgres_test_url()
    database_a = Database(raw_url)
    database_b = Database(raw_url)
    await database_a.drop_schema()
    await database_a.create_schema()
    await ProjectService(database_a).ensure_default()
    async with database_a.session() as session:
        session.add(
            CaseORM(
                id="case_job",
                project_id="default",
                name="Durable job",
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
                id="run_jobs",
                project_id="default",
                status="queued",
                selection_snapshot={},
                resolved_case_ids=["case_job"],
                profile_snapshot={},
                target_snapshots=[],
                total_count=2,
                completed_count=0,
                failed_count=0,
                skipped_count=0,
                cancelled_count=0,
            )
        )
        await session.flush()
        for index in (1, 2):
            session.add(
                CaseRunORM(
                    id=f"case_run_job_{index}",
                    project_id="default",
                    run_id="run_jobs",
                    case_id="case_job",
                    case_snapshot={"id": "case_job"},
                    target_snapshot={"id": "target", "driver_type": "test"},
                    profile_snapshot={},
                    repeat_index=index,
                    status="queued",
                    primary_evaluator="rule",
                    evaluation_state="awaiting_verdict",
                    summary={},
                )
            )
        await session.commit()

    config = ExecutionConfig(job_lease_seconds=10, worker_registration_ttl_seconds=30)
    jobs_a = DurableJobService(database_a, config)
    jobs_b = DurableJobService(database_b, config)
    try:
        await asyncio.gather(
            jobs_a.register_worker("worker-a"),
            jobs_b.register_worker("worker-b"),
        )
        job = await jobs_a.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_jobs",
                case_run_id="case_run_job_1",
                idempotency_key="postgres-job-1",
            ),
        )
        claims = await asyncio.gather(
            jobs_a.claim("worker-a"),
            jobs_b.claim("worker-b"),
        )
        leases = [item for item in claims if item is not None]
        assert len(leases) == 1
        original = leases[0]
        assert original.job.id == job.id

        async with database_a.session() as session:
            await session.execute(
                update(ExecutionJobORM)
                .where(ExecutionJobORM.id == job.id)
                .values(lease_expires_at=utc_now() - timedelta(seconds=1))
            )
            await session.commit()
        reaped = await jobs_b.reap_expired()
        assert reaped.requeued == 1
        async with database_a.session() as session:
            await session.execute(
                update(ExecutionJobORM)
                .where(ExecutionJobORM.id == job.id)
                .values(available_at=utc_now() - timedelta(seconds=1))
            )
            await session.commit()
        replacement = await jobs_b.claim("worker-b")
        assert replacement is not None
        assert replacement.job.id == job.id
        assert replacement.attempt.attempt == 2
        with pytest.raises(AgentRigError):
            await jobs_a.complete("default", job.id, original.lease_token)
        completed = await jobs_b.complete("default", job.id, replacement.lease_token)
        assert completed.status == "completed"

        side_effect_job = await jobs_a.enqueue(
            "default",
            ExecutionJobCreate(
                run_id="run_jobs",
                case_run_id="case_run_job_2",
                idempotency_key="postgres-job-2",
            ),
        )
        side_effect_lease = await jobs_a.claim("worker-a")
        assert side_effect_lease is not None
        await jobs_a.mark_external_side_effect_by_attempt(
            side_effect_lease.attempt.id,
        )
        async with database_a.session() as session:
            await session.execute(
                update(ExecutionJobORM)
                .where(ExecutionJobORM.id == side_effect_job.id)
                .values(lease_expires_at=utc_now() - timedelta(seconds=1))
            )
            await session.commit()
        side_effect_reap = await jobs_b.reap_expired()
        assert side_effect_reap.side_effect_dead == 1
        assert (await jobs_a.get("default", side_effect_job.id)).status == "dead"

        notifications: list[RunView] = []

        async def record_completion(run: RunView) -> None:
            notifications.append(run)

        worker_a = DurableWorker(
            jobs_a,
            cast(CaseExecutor, object()),
            SqlRunRepository(database_a),
            config,
        )
        worker_b = DurableWorker(
            jobs_b,
            cast(CaseExecutor, object()),
            SqlRunRepository(database_b),
            config,
        )
        worker_a.add_completion_listener(record_completion)
        worker_b.add_completion_listener(record_completion)
        await asyncio.gather(
            worker_a.finalize_run("default", "run_jobs"),
            worker_b.finalize_run("default", "run_jobs"),
        )
        finalized = await SqlRunRepository(database_a).get_run("run_jobs")
        assert finalized is not None
        assert finalized.status is RunStatus.FAILED
        assert len(notifications) == 1
    finally:
        await database_a.dispose()
        await database_b.dispose()
        cleanup = Database(raw_url)
        await cleanup.drop_schema()
        await cleanup.dispose()


async def test_postgresql_otlp_ingest_and_retention_round_trip() -> None:
    raw_url = _postgres_test_url()
    database = Database(raw_url)
    await database.drop_schema()
    await database.create_schema()
    await ProjectService(database).ensure_default()
    service = ProductionEvidenceService(
        database,
        config=ProductionEvidenceConfig(enabled=True, max_retention_delete_traces=100),
        redactor=Redactor(),
    )
    try:
        issued = await service.create_source(
            "default",
            IngestSourceCreate(
                name="postgres-collector",
                allowed_service_names=["postgres-agent"],
                retention_days=1,
                enabled=True,
            ),
        )
        result = await service.ingest_otlp(
            project_id="default",
            source_id=issued.source.id,
            token=issued.token,
            body=_postgres_otlp_payload(),
        )
        assert result.accepted_spans == 1
        dry_run = await service.run_retention(
            "default",
            ProductionRetentionRequest(
                source_id=issued.source.id,
                actor="postgres-retention-test",
                dry_run=True,
            ),
            now=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        assert (dry_run.trace_count, dry_run.span_count) == (1, 1)
        applied = await service.run_retention(
            "default",
            ProductionRetentionRequest(
                source_id=issued.source.id,
                actor="postgres-retention-test",
                dry_run=False,
            ),
            now=datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        assert (applied.trace_count, applied.tombstone_count) == (1, 1)
        assert (await service.list_traces("default")).total == 0
    finally:
        await database.dispose()
        cleanup = Database(raw_url)
        await cleanup.drop_schema()
        await cleanup.dispose()


def _postgres_otlp_payload() -> bytes:
    request = trace_service_pb2.ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    service = resource_spans.resource.attributes.add()
    service.key = "service.name"
    service.value.string_value = "postgres-agent"
    scope_spans = resource_spans.scope_spans.add()
    scope_spans.scope.name = "postgres-integration"
    span = scope_spans.spans.add()
    span.trace_id = bytes.fromhex("11" * 16)
    span.span_id = bytes.fromhex("22" * 8)
    span.name = "agent request"
    span.start_time_unix_nano = 1_704_067_200_000_000_000
    span.end_time_unix_nano = 1_704_067_201_000_000_000
    return request.SerializeToString()


def _postgres_test_url() -> str:
    raw_url = os.environ.get("AGENTRIG_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("AGENTRIG_TEST_POSTGRES_URL is not configured")
    database_name = make_url(raw_url).database or ""
    if "test" not in database_name.lower():
        pytest.skip("PostgreSQL integration database name must contain 'test'")
    return raw_url
