"""Project-scoped production evidence repository and reviewed asset conversion."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from google.protobuf.message import DecodeError  # type: ignore[import-untyped]
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..canonical import canonical_hash
from ..cases import CaseService, TestCaseCreate, TestTurn
from ..config import ProductionEvidenceConfig
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..infrastructure.database.orm import (
    AnnotationORM,
    FailurePatternORM,
    GovernanceAuditEventORM,
    IngestSourceORM,
    ProductionSessionORM,
    ProductionSpanORM,
    ProductionTraceORM,
    ReviewItemORM,
    TestCaseORM,
    TraceCaseLineageORM,
    utc_now,
)
from ..infrastructure.database.repositories import SqlCaseRepository
from ..infrastructure.database.session import Database
from ..runs.redactor import Redactor
from .otlp import count_spans, normalized_spans, parse_export_request
from .schemas import (
    IngestSourceCreate,
    IngestSourceIssue,
    IngestSourceView,
    OtlpIngestResult,
    ProductionRetentionRequest,
    ProductionRetentionResult,
    ProductionRetentionSourceResult,
    ProductionSessionView,
    ProductionSpanView,
    ProductionTraceDetail,
    ProductionTracePage,
    ProductionTraceView,
    TraceCaseDraftPreview,
    TraceCaseDraftRequest,
    TraceCaseDraftResult,
    TraceCaseLineageReview,
    TraceCaseLineageView,
)


class ProductionEvidenceService:
    def __init__(
        self,
        database: Database,
        *,
        config: ProductionEvidenceConfig,
        redactor: Redactor,
    ) -> None:
        self._database = database
        self._config = config
        self._redactor = redactor
        self._rate_windows: dict[str, deque[datetime]] = defaultdict(deque)

    async def create_source(
        self,
        project_id: str,
        value: IngestSourceCreate,
    ) -> IngestSourceIssue:
        if value.enabled and not self._config.enabled:
            raise AgentRigError(
                ErrorCode.PERMISSION_DENIED,
                "production ingest is disabled by deployment configuration",
            )
        token_secret = secrets.token_urlsafe(32)
        prefix = secrets.token_hex(5)
        token = f"aing_{prefix}_{token_secret}"
        row = IngestSourceORM(
            id=new_id("ingest"),
            project_id=project_id,
            name=value.name,
            source_type=value.source_type,
            api_key_hash=self._token_hash(token),
            key_prefix=prefix,
            allowed_service_names=value.allowed_service_names,
            redaction_policy=value.redaction_policy.model_dump(mode="json"),
            retention_days=value.retention_days,
            rate_limit_per_minute=value.rate_limit_per_minute,
            daily_span_quota=value.daily_span_quota,
            enabled=value.enabled,
        )
        async with self._database.session() as session:
            session.add(row)
            try:
                await session.commit()
            except Exception as exc:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "ingest source name already exists in project",
                ) from exc
            await session.refresh(row)
        return IngestSourceIssue(source=self._source_view(row), token=token)

    async def list_sources(self, project_id: str) -> list[IngestSourceView]:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(IngestSourceORM)
                    .where(IngestSourceORM.project_id == project_id)
                    .order_by(IngestSourceORM.created_at)
                )
            )
        return [self._source_view(row) for row in rows]

    async def set_source_enabled(
        self,
        project_id: str,
        source_id: str,
        *,
        enabled: bool,
    ) -> IngestSourceView:
        if enabled and not self._config.enabled:
            raise AgentRigError(
                ErrorCode.PERMISSION_DENIED,
                "production ingest is disabled by deployment configuration",
            )
        async with self._database.session() as session:
            row = await session.scalar(
                select(IngestSourceORM).where(
                    IngestSourceORM.id == source_id,
                    IngestSourceORM.project_id == project_id,
                )
            )
            if row is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "ingest source not found")
            row.enabled = enabled
            await session.commit()
            return self._source_view(row)

    async def ingest_otlp(
        self,
        *,
        project_id: str,
        source_id: str,
        token: str,
        body: bytes,
    ) -> OtlpIngestResult:
        if not self._config.enabled:
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "production ingest is disabled")
        if len(body) > self._config.max_request_bytes:
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "OTLP request exceeds byte limit")
        source = await self._authenticate_source(project_id, source_id, token)
        self._check_rate_limit(source)
        try:
            request = parse_export_request(body)
        except DecodeError as exc:
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "malformed OTLP protobuf") from exc
        span_count = count_spans(request)
        if span_count > self._config.max_spans_per_request:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "OTLP request exceeds span batch limit",
            )
        used_today = await self._daily_span_count(source_id)
        if used_today + span_count > source.daily_span_quota:
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "daily ingest span quota exceeded")
        policy = source.redaction_policy
        spans = normalized_spans(
            request,
            project_id=project_id,
            policy=policy,
            redactor=self._redactor,
            max_attribute_count=self._config.max_attribute_count,
            max_attribute_value_chars=self._config.max_attribute_value_chars,
        )
        accepted = 0
        duplicates = 0
        rejected = 0
        conflicts = 0
        errors: list[str] = []
        for value in spans:
            if not value["external_trace_id"] or not value["external_span_id"]:
                rejected += 1
                errors.append("trace_id_or_span_id_missing")
                continue
            if value["service_name"] not in source.allowed_service_names:
                rejected += 1
                errors.append("service_name_not_allowed")
                continue
            outcome = await self._store_span(project_id, source, value)
            if outcome == "accepted":
                accepted += 1
            elif outcome == "duplicate":
                duplicates += 1
            else:
                rejected += 1
                conflicts += 1
                errors.append("span_id_content_conflict")
        async with self._database.session() as session:
            row = await session.get(IngestSourceORM, source.id)
            assert row is not None
            row.last_seen_at = utc_now()
            await session.commit()
        return OtlpIngestResult(
            accepted_spans=accepted,
            duplicate_spans=duplicates,
            rejected_spans=rejected,
            conflict_spans=conflicts,
            error_messages=sorted(set(errors)),
        )

    async def list_sessions(
        self,
        project_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProductionSessionView]:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(ProductionSessionORM)
                    .where(ProductionSessionORM.project_id == project_id)
                    .order_by(ProductionSessionORM.started_at.desc())
                    .limit(max(1, min(limit, 200)))
                    .offset(max(0, offset))
                )
            )
        return [self._session_view(row) for row in rows]

    async def list_traces(
        self,
        project_id: str,
        *,
        environment: str | None = None,
        service_name: str | None = None,
        trace_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProductionTracePage:
        filters: list[Any] = [ProductionTraceORM.project_id == project_id]
        if environment is not None:
            filters.append(ProductionTraceORM.environment == environment)
        if service_name is not None:
            filters.append(ProductionTraceORM.service_name == service_name)
        if trace_status is not None:
            filters.append(ProductionTraceORM.status == trace_status)
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(ProductionTraceORM.id)).where(*filters)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(ProductionTraceORM)
                    .where(*filters)
                    .order_by(ProductionTraceORM.started_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
        return ProductionTracePage(
            items=[self._trace_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_trace(self, project_id: str, trace_id: str) -> ProductionTraceDetail:
        async with self._database.session() as session:
            trace = await session.scalar(
                select(ProductionTraceORM).where(
                    ProductionTraceORM.id == trace_id,
                    ProductionTraceORM.project_id == project_id,
                )
            )
            if trace is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "production trace not found")
            spans = list(
                await session.scalars(
                    select(ProductionSpanORM)
                    .where(
                        ProductionSpanORM.trace_id == trace_id,
                        ProductionSpanORM.project_id == project_id,
                    )
                    .order_by(ProductionSpanORM.started_at, ProductionSpanORM.id)
                )
            )
        external_ids = {span.external_span_id for span in spans}
        missing_parents = sorted(
            {
                span.parent_external_span_id
                for span in spans
                if span.parent_external_span_id
                and span.parent_external_span_id not in external_ids
            }
        )
        return ProductionTraceDetail(
            trace=self._trace_view(trace),
            spans=[self._span_view(span) for span in spans],
            missing_parent_span_ids=missing_parents,
        )

    async def list_spans(
        self,
        project_id: str,
        trace_id: str,
    ) -> list[ProductionSpanView]:
        """Return a trace's ordered spans without crossing its Project boundary."""
        return (await self.get_trace(project_id, trace_id)).spans

    async def run_retention(
        self,
        project_id: str,
        value: ProductionRetentionRequest,
        *,
        now: datetime | None = None,
    ) -> ProductionRetentionResult:
        """Dry-run or apply source retention while preserving auditable lineage tombstones."""
        executed_at = self._as_utc(now or utc_now())
        async with self._database.session() as session:
            source_query = select(IngestSourceORM).where(
                IngestSourceORM.project_id == project_id
            )
            if value.source_id is not None:
                source_query = source_query.where(IngestSourceORM.id == value.source_id)
            sources = list(
                await session.scalars(source_query.order_by(IngestSourceORM.id))
            )
            if value.source_id is not None and not sources:
                raise AgentRigError(ErrorCode.NOT_FOUND, "ingest source not found")

            results: list[ProductionRetentionSourceResult] = []
            for source in sources:
                policy_cutoff = executed_at - timedelta(days=source.retention_days)
                requested_cutoff = (
                    self._as_utc(value.before) if value.before is not None else policy_cutoff
                )
                cutoff = min(policy_cutoff, requested_cutoff)
                base = (
                    select(ProductionTraceORM)
                    .where(
                        ProductionTraceORM.project_id == project_id,
                        ProductionTraceORM.source_id == source.id,
                        ProductionTraceORM.started_at < cutoff,
                    )
                    .order_by(ProductionTraceORM.started_at, ProductionTraceORM.id)
                )
                total = int(
                    await session.scalar(
                        select(func.count(ProductionTraceORM.id)).where(
                            ProductionTraceORM.project_id == project_id,
                            ProductionTraceORM.source_id == source.id,
                            ProductionTraceORM.started_at < cutoff,
                        )
                    )
                    or 0
                )
                traces = list(
                    await session.scalars(
                        base.limit(self._config.max_retention_delete_traces)
                    )
                )
                trace_ids = [item.id for item in traces]
                span_count = 0
                lineage_count = 0
                lineage_trace_ids: set[str] = set()
                session_ids = sorted(
                    {item.session_id for item in traces if item.session_id is not None}
                )
                if trace_ids:
                    span_count = int(
                        await session.scalar(
                            select(func.count(ProductionSpanORM.id)).where(
                                ProductionSpanORM.project_id == project_id,
                                ProductionSpanORM.trace_id.in_(trace_ids),
                            )
                        )
                        or 0
                    )
                    lineage_count = int(
                        await session.scalar(
                            select(func.count(TraceCaseLineageORM.id)).where(
                                TraceCaseLineageORM.project_id == project_id,
                                TraceCaseLineageORM.source_trace_id.in_(trace_ids),
                            )
                        )
                        or 0
                    )
                    lineage_trace_ids = set(
                        await session.scalars(
                            select(TraceCaseLineageORM.source_trace_id).where(
                                TraceCaseLineageORM.project_id == project_id,
                                TraceCaseLineageORM.source_trace_id.in_(trace_ids),
                            )
                        )
                    )

                removed_sessions = 0
                if not value.dry_run and trace_ids:
                    for trace in traces:
                        session.add(
                            GovernanceAuditEventORM(
                                id=new_id("audit"),
                                project_id=project_id,
                                aggregate_type="production_trace",
                                aggregate_id=trace.id,
                                event_type="retention_deleted",
                                actor=value.actor,
                                details={
                                    "source_id": source.id,
                                    "content_hash": trace.content_hash,
                                    "redaction_policy_hash": trace.redaction_policy_hash,
                                    "external_trace_id_hash": hashlib.sha256(
                                        trace.external_trace_id.encode("utf-8")
                                    ).hexdigest(),
                                    "started_at": self._as_utc(trace.started_at).isoformat(),
                                    "cutoff": cutoff.isoformat(),
                                    "lineage_preserved": trace.id in lineage_trace_ids,
                                },
                            )
                        )
                    await session.execute(
                        delete(ProductionSpanORM).where(
                            ProductionSpanORM.project_id == project_id,
                            ProductionSpanORM.trace_id.in_(trace_ids),
                        )
                    )
                    await session.execute(
                        delete(ProductionTraceORM).where(
                            ProductionTraceORM.project_id == project_id,
                            ProductionTraceORM.id.in_(trace_ids),
                        )
                    )
                    for session_id in session_ids:
                        production_session = await session.scalar(
                            select(ProductionSessionORM).where(
                                ProductionSessionORM.id == session_id,
                                ProductionSessionORM.project_id == project_id,
                                ProductionSessionORM.source_id == source.id,
                            )
                        )
                        if production_session is None:
                            continue
                        remaining = int(
                            await session.scalar(
                                select(func.count(ProductionTraceORM.id)).where(
                                    ProductionTraceORM.project_id == project_id,
                                    ProductionTraceORM.session_id == session_id,
                                )
                            )
                            or 0
                        )
                        production_session.trace_count = remaining
                        if remaining == 0:
                            await session.delete(production_session)
                            removed_sessions += 1
                    await session.flush()

                results.append(
                    ProductionRetentionSourceResult(
                        source_id=source.id,
                        cutoff=cutoff,
                        trace_count=len(trace_ids),
                        span_count=span_count,
                        session_count=(
                            len(session_ids) if value.dry_run else removed_sessions
                        ),
                        lineage_count=lineage_count,
                        tombstone_count=0 if value.dry_run else len(trace_ids),
                        truncated=total > len(trace_ids),
                    )
                )
            if not value.dry_run:
                await session.commit()

        return ProductionRetentionResult(
            project_id=project_id,
            dry_run=value.dry_run,
            sources=results,
            trace_count=sum(item.trace_count for item in results),
            span_count=sum(item.span_count for item in results),
            session_count=sum(item.session_count for item in results),
            lineage_count=sum(item.lineage_count for item in results),
            tombstone_count=sum(item.tombstone_count for item in results),
            executed_at=executed_at,
        )

    async def preview_case_draft(
        self,
        project_id: str,
        trace_id: str,
        value: TraceCaseDraftRequest,
    ) -> TraceCaseDraftPreview:
        detail = await self.get_trace(project_id, trace_id)
        available = {span.id: span for span in detail.spans}
        selected_ids = value.source_span_ids or sorted(available)
        if any(span_id not in available for span_id in selected_ids):
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                "selected production span not found in trace",
            )
        input_value = value.template_user_message or detail.trace.input_preview_redacted
        if not input_value:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "template_user_message is required when input preview was not retained",
            )
        generalized = self._generalize(input_value)
        expected = self._generalize(value.expected_behavior)
        mapping = {
            "trace_id": trace_id,
            "span_ids": selected_ids,
            "user_message": generalized,
            "expected_behavior": expected,
            "required_capabilities": sorted(value.required_capabilities),
            "target_versions": sorted(value.target_versions),
            "annotation_ids": sorted(value.annotation_ids),
            "failure_pattern_id": value.failure_pattern_id,
        }
        return TraceCaseDraftPreview(
            source_trace_id=trace_id,
            selected_span_ids=selected_ids,
            generalized_user_message=generalized,
            expected_behavior=expected,
            removed_fields=[
                "production_identity",
                "raw_input_output",
                "authorization",
                "hidden_thinking",
                "binary_artifacts",
            ],
            mapping_version="trace-to-case.v1",
            mapping_hash=canonical_hash(mapping),
        )

    async def create_case_draft(
        self,
        project_id: str,
        trace_id: str,
        value: TraceCaseDraftRequest,
    ) -> TraceCaseDraftResult:
        preview = await self.preview_case_draft(project_id, trace_id, value)
        await self._validate_lineage_refs(project_id, trace_id, preview.selected_span_ids, value)
        service = CaseService(SqlCaseRepository(self._database, project_id=project_id))
        case = await service.create(
            TestCaseCreate(
                name=f"Production trace regression {trace_id[:24]}",
                description=(
                    "Draft generated from reviewed production evidence; raw production "
                    "content is intentionally not copied."
                ),
                tags=[
                    "source.production-trace",
                    *[f"cap.{item.removeprefix('cap.')}" for item in value.required_capabilities],
                ],
                supported_versions=value.target_versions,
                primary_evaluator="evidence_judge",
                case_rubric=preview.expected_behavior,
                turns=[
                    TestTurn.model_validate(
                        {
                        "position": 1,
                        "user_message": preview.generalized_user_message,
                        "rubric": preview.expected_behavior,
                        }
                    )
                ],
            )
        )
        row = TraceCaseLineageORM(
            id=new_id("lineage"),
            project_id=project_id,
            source_trace_id=trace_id,
            source_span_ids=preview.selected_span_ids,
            annotation_ids=value.annotation_ids,
            failure_pattern_id=value.failure_pattern_id,
            draft_case_id=case.id,
            draft_sample_ids=[],
            mapping_version=preview.mapping_version,
            mapping_hash=preview.mapping_hash,
            created_by=value.created_by,
            status="draft",
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return TraceCaseDraftResult(
            preview=preview,
            case_id=case.id,
            lineage=self._lineage_view(row),
        )

    async def review_case_lineage(
        self,
        project_id: str,
        lineage_id: str,
        value: TraceCaseLineageReview,
    ) -> TraceCaseLineageView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TraceCaseLineageORM).where(
                    TraceCaseLineageORM.id == lineage_id,
                    TraceCaseLineageORM.project_id == project_id,
                )
            )
            if row is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "trace case lineage not found")
            if row.status != "draft":
                raise AgentRigError(ErrorCode.CONFLICT, "trace case lineage is immutable")
            if value.status == "approved":
                case = await session.scalar(
                    select(TestCaseORM).where(
                        TestCaseORM.id == row.draft_case_id,
                        TestCaseORM.project_id == project_id,
                    )
                )
                if case is None or case.review_status != "approved":
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "lineage approval requires its draft Case to be approved",
                    )
            row.status = value.status
            row.reviewed_by = value.reviewer_id
            session.add(
                GovernanceAuditEventORM(
                    id=new_id("audit"),
                    project_id=project_id,
                    aggregate_type="trace_case_lineage",
                    aggregate_id=row.id,
                    event_type=f"lineage_{value.status}",
                    actor=value.reviewer_id,
                    details={
                        "rationale": value.rationale,
                        "mapping_hash": row.mapping_hash,
                        "draft_case_id": row.draft_case_id,
                    },
                )
            )
            await session.commit()
            await session.refresh(row)
        return self._lineage_view(row)

    async def _validate_lineage_refs(
        self,
        project_id: str,
        trace_id: str,
        span_ids: list[str],
        value: TraceCaseDraftRequest,
    ) -> None:
        async with self._database.session() as session:
            if value.annotation_ids:
                valid_subject_ids = {trace_id, *span_ids}
                rows = set(
                    await session.scalars(
                        select(AnnotationORM.id)
                        .join(
                            ReviewItemORM,
                            ReviewItemORM.id == AnnotationORM.review_item_id,
                        )
                        .where(
                            AnnotationORM.project_id == project_id,
                            AnnotationORM.id.in_(value.annotation_ids),
                            ReviewItemORM.project_id == project_id,
                            ReviewItemORM.subject_type.in_(
                                ["production_trace", "production_span"]
                            ),
                            ReviewItemORM.subject_id.in_(valid_subject_ids),
                        )
                    )
                )
                if rows != set(value.annotation_ids):
                    raise AgentRigError(
                        ErrorCode.NOT_FOUND,
                        "one or more lineage annotations are invalid for this trace",
                    )
            if value.failure_pattern_id is not None:
                pattern_id = await session.scalar(
                    select(FailurePatternORM.id).where(
                        FailurePatternORM.id == value.failure_pattern_id,
                        FailurePatternORM.project_id == project_id,
                    )
                )
                if pattern_id is None:
                    raise AgentRigError(
                        ErrorCode.NOT_FOUND,
                        "failure pattern not found in project",
                    )

    async def _authenticate_source(
        self,
        project_id: str,
        source_id: str,
        token: str,
    ) -> IngestSourceView:
        parts = token.split("_", 2)
        if len(parts) != 3 or parts[0] != "aing":
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "invalid ingest credential")
        async with self._database.session() as session:
            row = await session.scalar(
                select(IngestSourceORM).where(
                    IngestSourceORM.id == source_id,
                    IngestSourceORM.project_id == project_id,
                    IngestSourceORM.key_prefix == parts[1],
                )
            )
        if (
            row is None
            or not row.enabled
            or not hmac.compare_digest(row.api_key_hash, self._token_hash(token))
        ):
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "invalid ingest credential")
        return self._source_view(row)

    def _check_rate_limit(self, source: IngestSourceView) -> None:
        now = utc_now()
        window = self._rate_windows[source.id]
        cutoff = now - timedelta(minutes=1)
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= source.rate_limit_per_minute:
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "ingest rate limit exceeded")
        window.append(now)

    async def _daily_span_count(self, source_id: str) -> int:
        now = utc_now()
        start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        async with self._database.session() as session:
            return int(
                await session.scalar(
                    select(func.count(ProductionSpanORM.id))
                    .join(
                        ProductionTraceORM,
                        ProductionTraceORM.id == ProductionSpanORM.trace_id,
                    )
                    .where(
                        ProductionTraceORM.source_id == source_id,
                        ProductionSpanORM.received_at >= start,
                    )
                )
                or 0
            )

    async def _store_span(
        self,
        project_id: str,
        source: IngestSourceView,
        value: dict[str, Any],
    ) -> str:
        async with self._database.session() as session:
            trace = await session.scalar(
                select(ProductionTraceORM).where(
                    ProductionTraceORM.project_id == project_id,
                    ProductionTraceORM.source_id == source.id,
                    ProductionTraceORM.external_trace_id == value["external_trace_id"],
                )
            )
            if trace is None:
                production_session = await self._session_for_span(
                    session,
                    project_id,
                    source.id,
                    value,
                )
                stable_trace = {
                    "project_id": project_id,
                    "source_id": source.id,
                    "external_trace_id": value["external_trace_id"],
                    "service_name": value["service_name"],
                    "environment": value["environment"],
                    "release": value["release"],
                }
                trace = ProductionTraceORM(
                    id=new_id("ptrace"),
                    project_id=project_id,
                    source_id=source.id,
                    session_id=(production_session.id if production_session else None),
                    external_trace_id=value["external_trace_id"],
                    root_span_id=(
                        value["external_span_id"]
                        if value["parent_external_span_id"] is None
                        else None
                    ),
                    name=value["name"],
                    started_at=value["started_at"],
                    ended_at=value["ended_at"],
                    status=value["status"],
                    service_name=value["service_name"],
                    environment=value["environment"],
                    release=value["release"],
                    input_preview_redacted=value["input_preview_redacted"],
                    output_preview_redacted=value["output_preview_redacted"],
                    attributes=value["attributes"],
                    token_usage=value["token_usage"],
                    ingest_status="partial",
                    content_hash=canonical_hash(stable_trace),
                    redaction_policy_hash=canonical_hash(
                        source.redaction_policy.model_dump(mode="json")
                    ),
                )
                session.add(trace)
                if production_session is not None:
                    production_session.trace_count += 1
                await session.flush()
            existing = await session.scalar(
                select(ProductionSpanORM).where(
                    ProductionSpanORM.trace_id == trace.id,
                    ProductionSpanORM.external_span_id == value["external_span_id"],
                )
            )
            if existing is not None:
                return (
                    "duplicate"
                    if existing.content_hash == value["content_hash"]
                    else "conflict"
                )
            session.add(
                ProductionSpanORM(
                    id=new_id("pspan"),
                    project_id=project_id,
                    trace_id=trace.id,
                    external_span_id=value["external_span_id"],
                    parent_external_span_id=value["parent_external_span_id"],
                    span_kind=value["span_kind"],
                    name=value["name"],
                    started_at=value["started_at"],
                    ended_at=value["ended_at"],
                    status=value["status"],
                    agent_path=value["agent_path"],
                    model_call=value["model_call"],
                    tool_call=value["tool_call"],
                    tool_result=value["tool_result"],
                    permission=value["permission"],
                    memory_operation=value["memory_operation"],
                    artifact_refs=value["artifact_refs"],
                    attributes=value["attributes"],
                    events=value["events"],
                    content_hash=value["content_hash"],
                )
            )
            if value["parent_external_span_id"] is None and trace.root_span_id is None:
                trace.root_span_id = value["external_span_id"]
            if value["ended_at"] > (trace.ended_at or trace.started_at):
                trace.ended_at = value["ended_at"]
            if value["status"] == "error":
                trace.status = "error"
            await session.commit()
        return "accepted"

    async def _session_for_span(
        self,
        session: AsyncSession,
        project_id: str,
        source_id: str,
        value: dict[str, Any],
    ) -> ProductionSessionORM | None:
        external_hash = value.get("external_session_id_hash")
        if not external_hash:
            return None
        row = await session.scalar(
            select(ProductionSessionORM).where(
                ProductionSessionORM.project_id == project_id,
                ProductionSessionORM.source_id == source_id,
                ProductionSessionORM.external_session_id_hash == external_hash,
            )
        )
        if row is not None:
            return row
        row = ProductionSessionORM(
            id=new_id("psession"),
            project_id=project_id,
            source_id=source_id,
            external_session_id_hash=external_hash,
            started_at=value["started_at"],
            ended_at=value["ended_at"],
            environment=value["environment"],
            release=value["release"],
            user_identity_hash=value["user_identity_hash"],
            trace_count=0,
            status="observed",
            attributes={},
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    def _generalize(value: str) -> str:
        value = re.sub(
            r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            "<email>",
            value,
        )
        value = re.sub(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b",
            "<id>",
            value,
        )
        value = re.sub(r"\b\d{8,}\b", "<number>", value)
        value = re.sub(
            r"(?i)(authorization|cookie|api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            value,
        )
        return value

    @staticmethod
    def _token_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _source_view(row: IngestSourceORM) -> IngestSourceView:
        return IngestSourceView.model_validate(
            {
                "id": row.id,
                "project_id": row.project_id,
                "name": row.name,
                "source_type": row.source_type,
                "key_prefix": row.key_prefix,
                "allowed_service_names": row.allowed_service_names,
                "redaction_policy": row.redaction_policy,
                "retention_days": row.retention_days,
                "rate_limit_per_minute": row.rate_limit_per_minute,
                "daily_span_quota": row.daily_span_quota,
                "enabled": row.enabled,
                "created_at": row.created_at,
                "last_seen_at": row.last_seen_at,
            }
        )

    @staticmethod
    def _session_view(row: ProductionSessionORM) -> ProductionSessionView:
        return ProductionSessionView.model_validate(row, from_attributes=True)

    @staticmethod
    def _trace_view(row: ProductionTraceORM) -> ProductionTraceView:
        return ProductionTraceView.model_validate(row, from_attributes=True)

    @staticmethod
    def _span_view(row: ProductionSpanORM) -> ProductionSpanView:
        return ProductionSpanView.model_validate(row, from_attributes=True)

    @staticmethod
    def _lineage_view(row: TraceCaseLineageORM) -> TraceCaseLineageView:
        return TraceCaseLineageView.model_validate(row, from_attributes=True)
