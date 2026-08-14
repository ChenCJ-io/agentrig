from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from sqlalchemy import func, select

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCasePatch
from agentrig.cases.models import ReviewStatus
from agentrig.config import ProductionEvidenceConfig, Settings
from agentrig.errors import AgentRigError
from agentrig.infrastructure.database.orm import (
    GovernanceAuditEventORM,
    ProductionSpanORM,
    TraceCaseLineageORM,
)
from agentrig.infrastructure.database.session import Database
from agentrig.production import (
    IngestSourceCreate,
    ProductionEvidenceService,
    ProductionRetentionRequest,
    TraceCaseDraftRequest,
    TraceCaseLineageReview,
)
from agentrig.production.otlp import export_response
from agentrig.production.schemas import RedactionPolicy
from agentrig.profiles import ProfileCreate
from agentrig.projects import ProjectCreate, ProjectService
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolResult,
)


class _ReplayDriver:
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            permission_observation=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(id=context.case_run_id)

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, object]:
        del context, session
        return {
            "source_status": "observed",
            "runtime": {
                "framework": "production-replay-fixture",
                "framework_version": "1",
            },
            "features": {
                name: {"status": "observed", "value": value}
                for name, value in self.capabilities().model_dump().items()
            },
        }

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        del session, message
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_TEXT_DELTA,
            text="The request fails safely without leaking credentials.",
        )
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session, results
        if False:
            yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


def _attribute(target: object, key: str, value: object) -> None:
    item = target.attributes.add()  # type: ignore[attr-defined]
    item.key = key
    if isinstance(value, bool):
        item.value.bool_value = value
    elif isinstance(value, int):
        item.value.int_value = value
    else:
        item.value.string_value = str(value)


def _otlp_payload(
    *,
    name: str = "agent request",
    include_rejected_service: bool = False,
) -> bytes:
    request = trace_service_pb2.ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    _attribute(resource_spans.resource, "service.name", "checkout-agent")
    _attribute(resource_spans.resource, "service.version", "2.4.0")
    _attribute(resource_spans.resource, "deployment.environment.name", "production")
    _attribute(resource_spans.resource, "authorization", "Bearer top-secret")
    _attribute(resource_spans.resource, "cookie", "session=top-secret")
    scope_spans = resource_spans.scope_spans.add()
    scope_spans.scope.name = "agentrig-test"
    span = scope_spans.spans.add()
    span.trace_id = bytes.fromhex("01" * 16)
    span.span_id = bytes.fromhex("02" * 8)
    span.name = name
    span.start_time_unix_nano = 1_704_067_200_000_000_000
    span.end_time_unix_nano = 1_704_067_201_000_000_000
    span.status.code = 2
    _attribute(span, "gen_ai.operation.name", "chat")
    _attribute(span, "gen_ai.request.model", "model-a")
    _attribute(span, "gen_ai.usage.input_tokens", 12)
    _attribute(span, "gen_ai.usage.output_tokens", 4)
    _attribute(
        span,
        "gen_ai.prompt",
        "email dev@example.com Authorization: Bearer top-secret cookie=session-secret",
    )
    _attribute(span, "gen_ai.completion", "secret=top-secret safe response")
    _attribute(span, "hidden_thinking", "private chain of thought")
    _attribute(span, "gen_ai.conversation.id", "customer-session-42")

    if include_rejected_service:
        second = request.resource_spans.add()
        _attribute(second.resource, "service.name", "unapproved-service")
        second_scope = second.scope_spans.add()
        rejected = second_scope.spans.add()
        rejected.trace_id = bytes.fromhex("03" * 16)
        rejected.span_id = bytes.fromhex("04" * 8)
        rejected.name = "rejected"
        rejected.start_time_unix_nano = span.start_time_unix_nano
        rejected.end_time_unix_nano = span.end_time_unix_nano
    return request.SerializeToString()


async def _service() -> tuple[Database, ProductionEvidenceService, str, str]:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    projects = ProjectService(database)
    await projects.ensure_default()
    service = ProductionEvidenceService(
        database,
        config=ProductionEvidenceConfig(
            enabled=True,
            max_retention_delete_traces=100,
        ),
        redactor=Redactor(
            sensitive_keys=["authorization", "cookie", "api_key", "token", "secret"],
            sensitive_paths=[],
        ),
    )
    issue = await service.create_source(
        "default",
        IngestSourceCreate(
            name="collector",
            allowed_service_names=["checkout-agent"],
            enabled=True,
            retention_days=1,
            redaction_policy=RedactionPolicy(
                save_input_preview=True,
                save_output_preview=True,
            ),
        ),
    )
    return database, service, issue.source.id, issue.token


@pytest.mark.asyncio
async def test_otlp_partial_success_is_idempotent_redacted_and_project_scoped() -> None:
    database, service, source_id, token = await _service()
    try:
        payload = _otlp_payload(include_rejected_service=True)
        result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=payload,
        )
        assert (result.accepted_spans, result.rejected_spans) == (1, 1)
        wire = trace_service_pb2.ExportTraceServiceResponse()
        wire.ParseFromString(
            export_response(
                rejected_spans=result.rejected_spans,
                message="; ".join(result.error_messages),
            )
        )
        assert wire.partial_success.rejected_spans == 1
        assert "service_name_not_allowed" in wire.partial_success.error_message

        duplicate = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=payload,
        )
        assert duplicate.duplicate_spans == 1
        assert duplicate.accepted_spans == 0

        conflict = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=_otlp_payload(name="same id, changed content"),
        )
        assert conflict.conflict_spans == 1
        page = await service.list_traces("default")
        assert page.total == 1
        detail = await service.get_trace("default", page.items[0].id)
        assert detail.trace.source_id == source_id
        assert detail.trace.content_hash.startswith("sha256:")
        persisted = detail.model_dump_json().casefold()
        assert "top-secret" not in persisted
        assert "private chain of thought" not in persisted
        assert "dev@example.com" not in persisted
        assert "[redacted]" in persisted
        assert detail.spans[0].model_call == {
            "operation": "chat",
            "model": "model-a",
        }

        projects = ProjectService(database)
        other = await projects.create(ProjectCreate(slug="other", name="Other"))
        with pytest.raises(AgentRigError):
            await service.get_trace(other.id, detail.trace.id)
        async with database.session() as session:
            assert int(await session.scalar(select(func.count(ProductionSpanORM.id))) or 0) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_trace_draft_and_retention_preserve_mapping_lineage_and_tombstone() -> None:
    database, service, source_id, token = await _service()
    try:
        result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=_otlp_payload(),
        )
        assert result.accepted_spans == 1
        trace = (await service.list_traces("default")).items[0]
        detail = await service.get_trace("default", trace.id)
        draft = await service.create_case_draft(
            "default",
            trace.id,
            TraceCaseDraftRequest(
                source_span_ids=[detail.spans[0].id],
                expected_behavior="The request fails safely without leaking credentials.",
                target_versions=["2.4.0"],
                required_capabilities=["permission_observation"],
                created_by="reviewer-a",
            ),
        )
        assert draft.lineage.status == "draft"
        assert draft.preview.mapping_hash == draft.lineage.mapping_hash
        assert draft.lineage.source_span_ids == [detail.spans[0].id]

        clock = datetime(2026, 8, 10, tzinfo=timezone.utc)
        dry_run = await service.run_retention(
            "default",
            ProductionRetentionRequest(
                source_id=source_id,
                actor="retention-worker",
                dry_run=True,
            ),
            now=clock,
        )
        assert (dry_run.trace_count, dry_run.span_count, dry_run.lineage_count) == (1, 1, 1)
        assert dry_run.tombstone_count == 0
        assert (await service.list_traces("default")).total == 1

        applied = await service.run_retention(
            "default",
            ProductionRetentionRequest(
                source_id=source_id,
                actor="retention-worker",
                dry_run=False,
            ),
            now=clock,
        )
        assert (applied.trace_count, applied.span_count, applied.tombstone_count) == (1, 1, 1)
        assert (await service.list_traces("default")).total == 0
        async with database.session() as session:
            lineage = await session.get(TraceCaseLineageORM, draft.lineage.id)
            assert lineage is not None
            assert lineage.mapping_hash == draft.preview.mapping_hash
            audit = await session.scalar(
                select(GovernanceAuditEventORM).where(
                    GovernanceAuditEventORM.aggregate_id == trace.id,
                    GovernanceAuditEventORM.event_type == "retention_deleted",
                )
            )
            assert audit is not None
            assert audit.details["lineage_preserved"] is True
            assert "external_trace_id" not in audit.details

        repeated = await service.run_retention(
            "default",
            ProductionRetentionRequest(
                source_id=source_id,
                actor="retention-worker",
                dry_run=False,
            ),
            now=clock,
        )
        assert repeated.trace_count == repeated.tombstone_count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_trace_case_draft_requires_review_then_replays_as_an_approved_case() -> None:
    database, production, source_id, token = await _service()
    container: ServiceContainer | None = None
    try:
        await production.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=_otlp_payload(),
        )
        trace = (await production.list_traces("default")).items[0]
        detail = await production.get_trace("default", trace.id)
        draft = await production.create_case_draft(
            "default",
            trace.id,
            TraceCaseDraftRequest(
                source_span_ids=[detail.spans[0].id],
                expected_behavior=(
                    "The request fails safely without leaking credentials."
                ),
                target_versions=["2.4.0"],
                required_capabilities=["permission_observation"],
                created_by="reviewer-a",
            ),
        )
        registry = DriverRegistry()
        registry.register("production_replay", _ReplayDriver)
        container = ServiceContainer.build(
            Settings(),
            database=database,
            drivers=registry,
        )
        await container.initialize()
        current = await container.cases.get(draft.case_id)
        await container.cases.update(
            draft.case_id,
            TestCasePatch(
                primary_evaluator="rule",
                turns=[
                    {
                        **current.turns[0].model_dump(mode="json"),
                        "assertions": [
                            {
                                "kind": "text_contains",
                                "value": "fails safely",
                            }
                        ],
                    }
                ],
            ),
        )
        await container.cases.review(draft.case_id, ReviewStatus.APPROVED)
        lineage = await production.review_case_lineage(
            "default",
            draft.lineage.id,
            TraceCaseLineageReview(
                status="approved",
                reviewer_id="reviewer-b",
                rationale="The generalized draft is safe and reproducible.",
            ),
        )
        assert lineage.status == "approved"
        assert lineage.mapping_hash == draft.preview.mapping_hash

        await container.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_production_replay",
                    "name": "Production replay fixture",
                    "driver_type": "production_replay",
                    "versions": [{"version": "2.4.0"}],
                }
            )
        )
        await container.profiles.create(
            ProfileCreate(
                id="profile_production_replay",
                name="Production replay",
            )
        )
        submitted = await container.runs.run_cases(
            RunCasesRequest.model_validate(
                {
                    "case_ids": [draft.case_id],
                    "targets": [
                        {
                            "target_id": "target_production_replay",
                            "version": "2.4.0",
                        }
                    ],
                    "profile_id": "profile_production_replay",
                }
            )
        )
        await container.scheduler.wait(submitted.run_id)
        run = await container.runs.get_run(submitted.run_id)
        case_runs = await container.runs.list_case_runs(submitted.run_id)

        assert run.status == "completed"
        assert case_runs.items[0].status == "completed"
        assert case_runs.items[0].evaluation_state == "pass"
    finally:
        if container is not None:
            await container.close()
        else:
            await database.dispose()
