"""Deterministic failure cohorts, lifecycle governance, and recurrence delivery."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, cast

import httpx
from sqlalchemy import func, select

from ..canonical import canonical_hash
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..infrastructure.database.orm import (
    AnnotationORM,
    CaseRunORM,
    EvaluationORM,
    FailureMonitorORM,
    FailureNotificationORM,
    FailurePatternEventORM,
    FailurePatternMembershipORM,
    FailurePatternORM,
    FailureSignalORM,
    ProductionTraceORM,
    RunORM,
    TestCaseORM,
    utc_now,
)
from ..infrastructure.database.session import Database
from ..infrastructure.http_policy import TargetHttpPolicy
from ..infrastructure.secrets import SecretResolver
from .schemas import (
    FailureLinksUpdate,
    FailureMonitorCreate,
    FailureMonitorView,
    FailurePatternCreate,
    FailurePatternPage,
    FailurePatternTransition,
    FailurePatternView,
    FailureSignalCreate,
    FailureSignalPage,
    FailureSignalView,
    MembershipReview,
    PatternDefinitionUpdate,
    PatternEventView,
    PatternMembershipView,
    WebhookDeliveryView,
)

_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"new", "ignored"},
    "new": {"ongoing", "escalating", "ignored"},
    "escalating": {"ongoing", "resolved", "ignored"},
    "ongoing": {"escalating", "resolved", "ignored"},
    "resolved": {"regressed"},
    "regressed": {"ongoing", "escalating", "resolved", "ignored"},
    "ignored": {"candidate", "new"},
}


class FailureGovernanceService:
    def __init__(
        self,
        database: Database,
        *,
        secrets: SecretResolver | None = None,
        http_policy: TargetHttpPolicy | None = None,
        webhook_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._database = database
        self._secrets = secrets or SecretResolver()
        self._http_policy = http_policy
        self._webhook_transport = webhook_transport

    async def ingest_signal(
        self, project_id: str, value: FailureSignalCreate
    ) -> FailureSignalView:
        snapshot_hash = await self._source_snapshot_hash(project_id, value)
        signature_payload = {
            "category": value.category.strip().lower(),
            "signal_type": value.signal_type.strip().lower(),
            "normalized_error_code": value.attributes.get("error_code"),
            "criterion": value.attributes.get("criterion"),
            "tool_name": value.attributes.get("tool_name"),
            "invariant": value.attributes.get("invariant"),
        }
        signature = canonical_hash(signature_payload)
        occurred_at = value.occurred_at or utc_now()
        async with self._database.session() as session:
            existing = await session.scalar(
                select(FailureSignalORM).where(
                    FailureSignalORM.project_id == project_id,
                    FailureSignalORM.source_type == value.source_kind,
                    FailureSignalORM.source_id == value.source_id,
                    FailureSignalORM.detector_version == value.detector_version,
                )
            )
            if existing is not None:
                if (
                    existing.source_snapshot_hash != snapshot_hash
                    or existing.signature != signature
                ):
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "failure signal idempotency conflict",
                    )
                return self._signal_view(existing)
            row = FailureSignalORM(
                id=new_id("signal"),
                project_id=project_id,
                source_type=value.source_kind,
                source_id=value.source_id,
                source_snapshot_hash=snapshot_hash,
                detector_version=value.detector_version,
                signature=signature,
                category=value.category,
                severity=value.severity,
                label=value.label,
                summary=value.summary,
                environment=value.environment,
                release=value.release,
                target_runtime=value.target_runtime,
                evidence_refs=value.evidence_refs,
                attributes={"signal_type": value.signal_type, **value.attributes},
                occurred_at=occurred_at,
            )
            session.add(row)
            await session.flush()
            await self._evaluate_recurrence(session, row)
            await session.commit()
            await session.refresh(row)
        return self._signal_view(row)

    async def list_signals(
        self,
        project_id: str,
        *,
        category: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> FailureSignalPage:
        filters: list[Any] = [FailureSignalORM.project_id == project_id]
        if category:
            filters.append(FailureSignalORM.category == category)
        if severity:
            filters.append(FailureSignalORM.severity == severity)
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(FailureSignalORM.id)).where(*filters))
                or 0
            )
            rows = list(
                await session.scalars(
                    select(FailureSignalORM)
                    .where(*filters)
                    .order_by(FailureSignalORM.occurred_at.desc(), FailureSignalORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return FailureSignalPage(
            items=[self._signal_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create_pattern(
        self, project_id: str, value: FailurePatternCreate
    ) -> FailurePatternView:
        async with self._database.session() as session:
            signals = list(
                await session.scalars(
                    select(FailureSignalORM).where(
                        FailureSignalORM.project_id == project_id,
                        FailureSignalORM.id.in_(value.signal_ids),
                    )
                )
            )
            if len(signals) != len(value.signal_ids):
                raise AgentRigError(ErrorCode.NOT_FOUND, "one or more failure signals not found")
            signatures = {row.signature for row in signals}
            categories = {row.category for row in signals}
            matcher = value.matcher or {
                "kind": "exact",
                "signature": sorted(signatures)[0] if len(signatures) == 1 else None,
            }
            pattern_signature = canonical_hash(
                {"category": sorted(categories), "matcher": matcher}
            )
            first_seen = min(row.occurred_at for row in signals)
            last_seen = max(row.occurred_at for row in signals)
            row = FailurePatternORM(
                id=new_id("pattern"),
                project_id=project_id,
                title=value.title,
                description=value.description,
                category=signals[0].category if len(categories) == 1 else "mixed",
                severity=value.severity,
                priority=value.priority,
                status="candidate",
                signature=pattern_signature,
                definition_version=1,
                matcher=matcher,
                owner=value.owner,
                representative_signal_ids=value.signal_ids,
                linked_case_ids=[],
                linked_suite_versions=[],
                linked_release_gate_ids=[],
                first_seen_at=first_seen,
                last_seen_at=last_seen,
            )
            session.add(row)
            await session.flush()
            for signal in signals:
                match_kind = (
                    "exact"
                    if matcher.get("kind") == "exact" and len(signatures) == 1
                    else "manual"
                )
                session.add(
                    FailurePatternMembershipORM(
                        pattern_id=row.id,
                        signal_id=signal.id,
                        definition_version=1,
                        membership_source=match_kind,
                        confidence=1.0 if match_kind == "exact" else None,
                        explanation="initial candidate cohort",
                        status="candidate",
                    )
                )
            self._event(
                session,
                row,
                "created",
                value.created_by,
                {"signal_ids": value.signal_ids, "definition_version": 1},
            )
            await session.commit()
        return await self.get_pattern(project_id, row.id)

    async def list_patterns(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> FailurePatternPage:
        filters: list[Any] = [FailurePatternORM.project_id == project_id]
        if status:
            filters.append(FailurePatternORM.status == status)
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(FailurePatternORM.id)).where(*filters))
                or 0
            )
            rows = list(
                await session.scalars(
                    select(FailurePatternORM)
                    .where(*filters)
                    .order_by(
                        FailurePatternORM.priority.desc(),
                        FailurePatternORM.last_seen_at.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            views = [await self._pattern_view(session, row) for row in rows]
        return FailurePatternPage(items=views, total=total, limit=limit, offset=offset)

    async def get_pattern(self, project_id: str, pattern_id: str) -> FailurePatternView:
        async with self._database.session() as session:
            row = await self._pattern_row(session, project_id, pattern_id)
            return await self._pattern_view(session, row)

    async def review_memberships(
        self,
        project_id: str,
        pattern_id: str,
        value: MembershipReview,
    ) -> FailurePatternView:
        async with self._database.session() as session:
            pattern = await self._pattern_row(session, project_id, pattern_id)
            for decision in value.decisions:
                row = await session.scalar(
                    select(FailurePatternMembershipORM).where(
                        FailurePatternMembershipORM.pattern_id == pattern_id,
                        FailurePatternMembershipORM.signal_id == decision.signal_id,
                    )
                )
                if row is None:
                    raise AgentRigError(ErrorCode.NOT_FOUND, "pattern membership not found")
                if row.status != "candidate":
                    raise AgentRigError(ErrorCode.CONFLICT, "membership was already reviewed")
                row.status = decision.decision
                row.accepted_by = value.reviewer_id
                row.explanation = decision.explanation
            self._event(
                session,
                pattern,
                "memberships_reviewed",
                value.reviewer_id,
                {"decisions": [item.model_dump(mode="json") for item in value.decisions]},
            )
            await session.commit()
        return await self.get_pattern(project_id, pattern_id)

    async def update_links(
        self, project_id: str, pattern_id: str, value: FailureLinksUpdate
    ) -> FailurePatternView:
        async with self._database.session() as session:
            pattern = await self._pattern_row(session, project_id, pattern_id)
            if value.linked_case_ids:
                found = set(
                    await session.scalars(
                        select(TestCaseORM.id).where(
                            TestCaseORM.project_id == project_id,
                            TestCaseORM.id.in_(value.linked_case_ids),
                        )
                    )
                )
                if found != set(value.linked_case_ids):
                    raise AgentRigError(ErrorCode.NOT_FOUND, "linked case not found")
            pattern.linked_case_ids = list(dict.fromkeys(value.linked_case_ids))
            pattern.linked_suite_versions = list(
                dict.fromkeys(value.linked_suite_versions)
            )
            pattern.linked_release_gate_ids = list(
                dict.fromkeys(value.linked_release_gate_ids)
            )
            pattern.release = value.release
            self._event(
                session,
                pattern,
                "links_updated",
                value.actor,
                value.model_dump(mode="json", exclude={"actor"}),
            )
            await session.commit()
        return await self.get_pattern(project_id, pattern_id)

    async def update_definition(
        self, project_id: str, pattern_id: str, value: PatternDefinitionUpdate
    ) -> FailurePatternView:
        async with self._database.session() as session:
            pattern = await self._pattern_row(session, project_id, pattern_id)
            pattern.definition_version += 1
            pattern.matcher = value.matcher
            pattern.signature = canonical_hash(
                {"category": pattern.category, "matcher": value.matcher}
            )
            self._event(
                session,
                pattern,
                "definition_updated",
                value.actor,
                {"definition_version": pattern.definition_version, "reason": value.reason},
            )
            await session.commit()
        return await self.get_pattern(project_id, pattern_id)

    async def transition(
        self, project_id: str, pattern_id: str, value: FailurePatternTransition
    ) -> FailurePatternView:
        async with self._database.session() as session:
            pattern = await self._pattern_row(session, project_id, pattern_id)
            if value.target_status not in _TRANSITIONS.get(pattern.status, set()):
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    f"illegal failure pattern transition: {pattern.status} -> {value.target_status}",
                )
            if value.target_status == "new":
                confirmed = int(
                    await session.scalar(
                        select(func.count(FailurePatternMembershipORM.signal_id)).where(
                            FailurePatternMembershipORM.pattern_id == pattern.id,
                            FailurePatternMembershipORM.status == "confirmed",
                        )
                    )
                    or 0
                )
                if not pattern.owner or confirmed == 0:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "confirmation requires an owner and a confirmed membership",
                    )
                pattern.confirmed_by = value.actor
            if value.target_status == "resolved":
                await self._verify_resolution(session, pattern, value.resolved_by_run_id or "")
                pattern.resolved_by_run_id = value.resolved_by_run_id
                pattern.resolved_at = utc_now()
            elif value.target_status == "ignored":
                pattern.ignored_reason = value.reason
                pattern.ignored_until = value.ignored_until
            elif value.target_status == "regressed":
                pattern.resolved_at = None
            pattern.status = value.target_status
            event_type = (
                "fix_verified" if value.target_status == "resolved" else value.target_status
            )
            self._event(
                session,
                pattern,
                event_type,
                value.actor,
                {
                    "reason": value.reason,
                    "resolved_by_run_id": value.resolved_by_run_id,
                },
            )
            await session.commit()
        return await self.get_pattern(project_id, pattern_id)

    async def create_monitor(
        self, project_id: str, pattern_id: str, value: FailureMonitorCreate
    ) -> FailureMonitorView:
        async with self._database.session() as session:
            pattern = await self._pattern_row(session, project_id, pattern_id)
            if pattern.status == "candidate":
                raise AgentRigError(
                    ErrorCode.CONFLICT, "candidate patterns cannot have active monitors"
                )
            config = value.webhook.model_dump(mode="json") if value.webhook else {}
            row = FailureMonitorORM(
                id=new_id("monitor"),
                project_id=project_id,
                pattern_id=pattern_id,
                definition_version=pattern.definition_version,
                status="active",
                environment=value.environment,
                shadow_mode=value.shadow_mode,
                recurrence_count=0,
                notification_config=config,
            )
            session.add(row)
            self._event(
                session,
                pattern,
                "monitor_created",
                pattern.confirmed_by or pattern.owner or "system",
                {"monitor_id": row.id, "shadow_mode": row.shadow_mode},
            )
            await session.commit()
            await session.refresh(row)
        return self._monitor_view(row)

    async def list_monitors(
        self, project_id: str, pattern_id: str
    ) -> list[FailureMonitorView]:
        async with self._database.session() as session:
            await self._pattern_row(session, project_id, pattern_id)
            rows = list(
                await session.scalars(
                    select(FailureMonitorORM)
                    .where(
                        FailureMonitorORM.project_id == project_id,
                        FailureMonitorORM.pattern_id == pattern_id,
                    )
                    .order_by(FailureMonitorORM.created_at)
                )
            )
        return [self._monitor_view(row) for row in rows]

    async def timeline(
        self, project_id: str, pattern_id: str
    ) -> list[PatternEventView]:
        async with self._database.session() as session:
            await self._pattern_row(session, project_id, pattern_id)
            rows = list(
                await session.scalars(
                    select(FailurePatternEventORM)
                    .where(
                        FailurePatternEventORM.project_id == project_id,
                        FailurePatternEventORM.pattern_id == pattern_id,
                    )
                    .order_by(FailurePatternEventORM.created_at, FailurePatternEventORM.id)
                )
            )
        return [PatternEventView.model_validate(row, from_attributes=True) for row in rows]

    async def dispatch_webhook(
        self, project_id: str, monitor_id: str, *, idempotency_key: str
    ) -> WebhookDeliveryView:
        async with self._database.session() as session:
            monitor = await session.scalar(
                select(FailureMonitorORM).where(
                    FailureMonitorORM.id == monitor_id,
                    FailureMonitorORM.project_id == project_id,
                )
            )
            if monitor is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "failure monitor not found")
            pattern = await self._pattern_row(session, project_id, monitor.pattern_id)
            existing = await session.scalar(
                select(FailureNotificationORM).where(
                    FailureNotificationORM.monitor_id == monitor_id,
                    FailureNotificationORM.idempotency_key == idempotency_key,
                )
            )
            if existing is not None and existing.status in {"delivered", "dead"}:
                return self._delivery_view(existing)
            config = monitor.notification_config
            if not config:
                raise AgentRigError(ErrorCode.CONFLICT, "monitor has no webhook configured")
            payload = {
                "schema_version": "agentrig.failure-webhook.v1",
                "pattern_id": pattern.id,
                "title": pattern.title,
                "severity": pattern.severity,
                "status": pattern.status,
                "release": self._safe_release(pattern.release),
                "recurrence_count": monitor.recurrence_count,
                "url_path": f"/failure-patterns/{pattern.id}",
            }
            row = existing or FailureNotificationORM(
                id=new_id("notify"),
                project_id=project_id,
                monitor_id=monitor.id,
                pattern_id=pattern.id,
                idempotency_key=idempotency_key,
                payload=payload,
                payload_hash=canonical_hash(payload),
                status="pending",
                attempts=0,
                max_attempts=int(config.get("max_attempts", 3)),
            )
            if existing is None:
                session.add(row)
            if row.attempts >= row.max_attempts:
                row.status = "dead"
                await session.commit()
                return self._delivery_view(row)
            secret = self._secrets.resolve(str(config["secret_ref"]))
            if not secret:
                raise AgentRigError(ErrorCode.PERMISSION_DENIED, "webhook secret unavailable")
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            row.attempts += 1
            await session.commit()
        try:
            url = str(config["url"])
            if self._http_policy is not None:
                await self._http_policy.authorize_url(url)
            async with httpx.AsyncClient(
                transport=self._webhook_transport, timeout=10, follow_redirects=False
            ) as client:
                response = await client.post(
                    url,
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-agentrig-signature": f"sha256={signature}",
                        "idempotency-key": idempotency_key,
                    },
                )
                response.raise_for_status()
            delivery_status, error = "delivered", None
        except Exception as exc:
            delivery_status, error = "failed", type(exc).__name__
        async with self._database.session() as session:
            current = await session.get(FailureNotificationORM, row.id)
            assert current is not None
            current.last_error = error
            if delivery_status == "delivered":
                current.status = "delivered"
                current.delivered_at = utc_now()
            else:
                current.status = "dead" if current.attempts >= current.max_attempts else "failed"
            await session.commit()
            await session.refresh(current)
            return self._delivery_view(current)

    async def _evaluate_recurrence(self, session: Any, signal: FailureSignalORM) -> None:
        monitors = list(
            await session.scalars(
                select(FailureMonitorORM).where(
                    FailureMonitorORM.project_id == signal.project_id,
                    FailureMonitorORM.status == "active",
                )
            )
        )
        for monitor in monitors:
            pattern = await session.get(FailurePatternORM, monitor.pattern_id)
            if pattern is None or monitor.definition_version != pattern.definition_version:
                continue
            matcher = pattern.matcher
            exact = matcher.get("kind") == "exact" and matcher.get("signature") == signal.signature
            rule = matcher.get("kind") == "rule" and all(
                signal.attributes.get(key) == expected
                for key, expected in dict(matcher.get("attributes", {})).items()
            )
            if not exact and not rule:
                continue
            if monitor.environment and signal.environment != monitor.environment:
                continue
            membership = await session.get(
                FailurePatternMembershipORM, (pattern.id, signal.id)
            )
            if membership is None:
                membership = FailurePatternMembershipORM(
                    pattern_id=pattern.id,
                    signal_id=signal.id,
                    definition_version=pattern.definition_version,
                    membership_source="exact" if exact else "rule",
                    confidence=1.0,
                    explanation="deterministic monitor match",
                    status="confirmed" if pattern.severity == "critical" else "candidate",
                    accepted_by="system" if pattern.severity == "critical" else None,
                )
                session.add(membership)
            monitor.last_checked_at = utc_now()
            monitor.last_seen_at = signal.occurred_at
            monitor.cursor = signal.id
            monitor.recurrence_count += 1
            pattern.last_seen_at = max(
                self._as_utc(pattern.last_seen_at),
                self._as_utc(signal.occurred_at),
            )
            self._event(
                session,
                pattern,
                "recurrence_matched",
                "system",
                {
                    "signal_id": signal.id,
                    "monitor_id": monitor.id,
                    "late_evidence": self._as_utc(signal.occurred_at)
                    < self._as_utc(pattern.resolved_at)
                    if pattern.resolved_at
                    else False,
                    "shadow_mode": monitor.shadow_mode,
                },
            )
            if (
                pattern.status == "resolved"
                and pattern.severity == "critical"
                and not monitor.shadow_mode
            ):
                pattern.status = "regressed"
                self._event(
                    session,
                    pattern,
                    "regressed",
                    "system",
                    {"signal_id": signal.id, "monitor_id": monitor.id},
                )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Normalize SQLite's naive DateTime values before ordering evidence."""
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    async def _source_snapshot_hash(
        self, project_id: str, value: FailureSignalCreate
    ) -> str:
        if value.source_kind == "manual":
            return canonical_hash(
                {
                    "source_id": value.source_id,
                    "summary": value.summary,
                    "evidence_refs": value.evidence_refs,
                    "attributes": value.attributes,
                }
            )
        async with self._database.session() as session:
            if value.source_kind == "evaluation":
                row = await session.scalar(
                    select(EvaluationORM)
                    .join(CaseRunORM, CaseRunORM.id == EvaluationORM.case_run_id)
                    .where(
                        EvaluationORM.id == value.source_id,
                        CaseRunORM.project_id == project_id,
                    )
                )
                if row:
                    return canonical_hash(
                        {
                            "id": row.id,
                            "status": row.status,
                            "verdict": row.verdict,
                            "criteria": row.criteria,
                            "evidence_refs": row.evidence_refs,
                            "config_snapshot": row.config_snapshot,
                        }
                    )
            elif value.source_kind == "annotation":
                row = await session.scalar(
                    select(AnnotationORM).where(
                        AnnotationORM.id == value.source_id,
                        AnnotationORM.project_id == project_id,
                    )
                )
                if row:
                    return canonical_hash(
                        {
                            "id": row.id,
                            "label": row.label,
                            "criteria": row.criteria,
                            "evidence_refs": row.evidence_refs,
                        }
                    )
            else:
                row = await session.scalar(
                    select(ProductionTraceORM).where(
                        ProductionTraceORM.id == value.source_id,
                        ProductionTraceORM.project_id == project_id,
                    )
                )
                if row:
                    return str(row.content_hash)
        raise AgentRigError(ErrorCode.NOT_FOUND, "failure signal source not found")

    async def _verify_resolution(
        self, session: Any, pattern: FailurePatternORM, run_id: str
    ) -> None:
        if not pattern.linked_case_ids or not pattern.linked_suite_versions:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "resolution requires linked approved cases and a suite version",
            )
        approved = set(
            await session.scalars(
                select(TestCaseORM.id).where(
                    TestCaseORM.project_id == pattern.project_id,
                    TestCaseORM.id.in_(pattern.linked_case_ids),
                    TestCaseORM.review_status == "approved",
                )
            )
        )
        if approved != set(pattern.linked_case_ids):
            raise AgentRigError(ErrorCode.CONFLICT, "all linked cases must be approved")
        run = await session.scalar(
            select(RunORM).where(
                RunORM.id == run_id,
                RunORM.project_id == pattern.project_id,
                RunORM.status == "completed",
            )
        )
        if run is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "completed verification run not found")
        verified = list(
            await session.scalars(
                select(CaseRunORM).where(
                    CaseRunORM.run_id == run_id,
                    CaseRunORM.project_id == pattern.project_id,
                    CaseRunORM.case_id.in_(pattern.linked_case_ids),
                    CaseRunORM.status == "completed",
                    CaseRunORM.evaluation_state == "pass",
                    CaseRunORM.capability_snapshot.is_not(None),
                )
            )
        )
        if {row.case_id for row in verified} != set(pattern.linked_case_ids):
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "verification run must pass every linked case with capability evidence",
            )

    async def _pattern_row(
        self, session: Any, project_id: str, pattern_id: str
    ) -> FailurePatternORM:
        row = await session.scalar(
            select(FailurePatternORM).where(
                FailurePatternORM.id == pattern_id,
                FailurePatternORM.project_id == project_id,
            )
        )
        if row is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "failure pattern not found")
        return cast(FailurePatternORM, row)

    async def _pattern_view(
        self, session: Any, row: FailurePatternORM
    ) -> FailurePatternView:
        memberships = list(
            await session.scalars(
                select(FailurePatternMembershipORM)
                .where(FailurePatternMembershipORM.pattern_id == row.id)
                .order_by(FailurePatternMembershipORM.created_at)
            )
        )
        return FailurePatternView(
            id=row.id,
            project_id=row.project_id,
            title=row.title,
            description=row.description,
            category=row.category,
            severity=cast(Any, row.severity),
            priority=row.priority,
            status=cast(Any, row.status),
            signature=row.signature,
            definition_version=row.definition_version,
            matcher=row.matcher,
            owner=row.owner,
            confirmed_by=row.confirmed_by,
            resolved_by_run_id=row.resolved_by_run_id,
            ignored_reason=row.ignored_reason,
            ignored_until=row.ignored_until,
            representative_signal_ids=row.representative_signal_ids,
            linked_case_ids=row.linked_case_ids,
            linked_suite_versions=row.linked_suite_versions,
            linked_release_gate_ids=row.linked_release_gate_ids,
            release=row.release,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            resolved_at=row.resolved_at,
            memberships=[
                PatternMembershipView(
                    pattern_id=item.pattern_id,
                    definition_version=item.definition_version,
                    signal_id=item.signal_id,
                    match_kind=cast(Any, item.membership_source),
                    match_score=item.confidence,
                    explanation=item.explanation,
                    status=cast(Any, item.status),
                    reviewed_by=item.accepted_by,
                    created_at=item.created_at,
                )
                for item in memberships
            ],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _event(
        session: Any,
        pattern: FailurePatternORM,
        event_type: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        session.add(
            FailurePatternEventORM(
                id=new_id("pevent"),
                project_id=pattern.project_id,
                pattern_id=pattern.id,
                event_type=event_type,
                actor=actor,
                details=details,
            )
        )

    @staticmethod
    def _safe_release(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        allowed = {"environment", "version", "git_sha", "build_id", "content_hash"}
        return {key: item for key, item in value.items() if key in allowed}

    @staticmethod
    def _signal_view(row: FailureSignalORM) -> FailureSignalView:
        return FailureSignalView(
            id=row.id,
            project_id=row.project_id,
            source_kind=row.source_type,
            source_id=row.source_id,
            source_snapshot_hash=row.source_snapshot_hash,
            signal_type=str(row.attributes.get("signal_type", row.category)),
            signature=row.signature,
            category=row.category,
            severity=cast(Any, row.severity),
            label=row.label,
            summary=row.summary,
            detector_version=row.detector_version,
            environment=row.environment,
            release=row.release,
            target_runtime=row.target_runtime,
            evidence_refs=row.evidence_refs,
            attributes={
                key: value for key, value in row.attributes.items() if key != "signal_type"
            },
            occurred_at=row.occurred_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _monitor_view(row: FailureMonitorORM) -> FailureMonitorView:
        return FailureMonitorView.model_validate(row, from_attributes=True)

    @staticmethod
    def _delivery_view(row: FailureNotificationORM) -> WebhookDeliveryView:
        return WebhookDeliveryView.model_validate(row, from_attributes=True)
