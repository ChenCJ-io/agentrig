"""Append-only human review and deterministic Judge alignment service."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

from sqlalchemy import func, select

from ..canonical import canonical_hash
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..infrastructure.database.orm import (
    AlignmentRunORM,
    AnnotationORM,
    CaseRunORM,
    EvaluatorVersionORM,
    GoldLabelORM,
    GovernanceAuditEventORM,
    ProductionSpanORM,
    ProductionTraceORM,
    ReviewItemORM,
    RunEventORM,
    utc_now,
)
from ..infrastructure.database.session import Database
from .schemas import (
    AlignmentMetrics,
    AlignmentPrediction,
    AlignmentReport,
    AlignmentRunCreate,
    AnnotationCreate,
    AnnotationCriterion,
    AnnotationView,
    EvaluatorActivate,
    EvaluatorVersionCreate,
    EvaluatorVersionView,
    GoldLabelResolve,
    GoldLabelView,
    ReviewItemCreate,
    ReviewItemPage,
    ReviewItemView,
    ReviewLabel,
)

_LABELS = ("pass", "fail", "inconclusive", "evaluation_error")


class ReviewAlignmentService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_review_item(
        self, project_id: str, value: ReviewItemCreate
    ) -> ReviewItemView:
        snapshot_hash = await self._subject_snapshot_hash(
            project_id, value.subject_kind, value.subject_id
        )
        row = ReviewItemORM(
            id=new_id("review"),
            project_id=project_id,
            subject_type=value.subject_kind,
            subject_id=value.subject_id,
            subject_snapshot_hash=snapshot_hash,
            queue=value.queue,
            priority=value.priority,
            assignment=value.assignment,
            cohort=value.cohort,
            status="open",
            required_reviews=value.required_reviews,
            created_reason=value.created_reason,
            created_by=value.created_by,
        )
        async with self._database.session() as session:
            session.add(row)
            self._audit(
                session,
                project_id,
                "review_item",
                row.id,
                "created",
                value.created_by,
                {"subject_snapshot_hash": snapshot_hash},
            )
            await session.commit()
            await session.refresh(row)
        return self._review_view(row)

    async def list_review_items(
        self,
        project_id: str,
        *,
        status: str | None = None,
        queue: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReviewItemPage:
        filters: list[Any] = [ReviewItemORM.project_id == project_id]
        if status:
            filters.append(ReviewItemORM.status == status)
        if queue:
            filters.append(ReviewItemORM.queue == queue)
        limit, offset = max(1, min(limit, 200)), max(0, offset)
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(ReviewItemORM.id)).where(*filters))
                or 0
            )
            rows = list(
                await session.scalars(
                    select(ReviewItemORM)
                    .where(*filters)
                    .order_by(
                        ReviewItemORM.priority.desc(),
                        ReviewItemORM.created_at,
                        ReviewItemORM.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return ReviewItemPage(
            items=[self._review_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def add_annotation(
        self,
        project_id: str,
        review_item_id: str,
        value: AnnotationCreate,
    ) -> AnnotationView:
        async with self._database.session() as session:
            item = await self._review_row(session, project_id, review_item_id)
            if item.status in {"resolved", "dismissed"}:
                raise AgentRigError(ErrorCode.CONFLICT, "review item is terminal")
            await self._validate_evidence_refs(session, project_id, item, value.evidence_refs)
            if value.supersedes:
                previous = await session.scalar(
                    select(AnnotationORM).where(
                        AnnotationORM.id == value.supersedes,
                        AnnotationORM.project_id == project_id,
                        AnnotationORM.review_item_id == review_item_id,
                    )
                )
                if previous is None:
                    raise AgentRigError(ErrorCode.NOT_FOUND, "superseded annotation not found")
                if previous.annotator_id != value.reviewer_id:
                    raise AgentRigError(
                        ErrorCode.PERMISSION_DENIED,
                        "reviewers may only supersede their own annotations",
                    )
                already_superseded = await session.scalar(
                    select(AnnotationORM.id).where(
                        AnnotationORM.supersedes_id == value.supersedes
                    )
                )
                if already_superseded is not None:
                    raise AgentRigError(ErrorCode.CONFLICT, "annotation already superseded")
            revision = int(
                await session.scalar(
                    select(func.max(AnnotationORM.revision)).where(
                        AnnotationORM.review_item_id == review_item_id
                    )
                )
                or 0
            ) + 1
            row = AnnotationORM(
                id=new_id("ann"),
                project_id=project_id,
                review_item_id=review_item_id,
                revision=revision,
                label=value.label,
                criteria=[item.model_dump(mode="json") for item in value.criteria],
                rationale=value.rationale_summary,
                evidence_refs=value.evidence_refs,
                annotator_id=value.reviewer_id,
                confidence=value.confidence,
                status="submitted",
                supersedes_id=value.supersedes,
            )
            session.add(row)
            item.status = "in_review"
            self._audit(
                session,
                project_id,
                "review_item",
                review_item_id,
                "annotation_submitted",
                value.reviewer_id,
                {"annotation_id": row.id, "revision": revision},
            )
            await session.commit()
            await session.refresh(row)
        return self._annotation_view(row)

    async def list_annotations(
        self, project_id: str, review_item_id: str
    ) -> list[AnnotationView]:
        async with self._database.session() as session:
            await self._review_row(session, project_id, review_item_id)
            rows = list(
                await session.scalars(
                    select(AnnotationORM)
                    .where(
                        AnnotationORM.project_id == project_id,
                        AnnotationORM.review_item_id == review_item_id,
                    )
                    .order_by(AnnotationORM.revision)
                )
            )
        return [self._annotation_view(row) for row in rows]

    async def resolve(
        self,
        project_id: str,
        review_item_id: str,
        value: GoldLabelResolve,
    ) -> GoldLabelView:
        async with self._database.session() as session:
            item = await self._review_row(session, project_id, review_item_id)
            if item.status in {"resolved", "dismissed"}:
                raise AgentRigError(ErrorCode.CONFLICT, "review item is terminal")
            rows = list(
                await session.scalars(
                    select(AnnotationORM)
                    .where(
                        AnnotationORM.project_id == project_id,
                        AnnotationORM.review_item_id == review_item_id,
                    )
                    .order_by(AnnotationORM.revision)
                )
            )
            current = self._current_annotations(rows)
            if len(current) < item.required_reviews:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "required independent reviews have not been submitted",
                    details={"required": item.required_reviews, "current": len(current)},
                )
            labels = {row.label for row in current}
            disputed = len(labels) > 1
            if (disputed or item.required_reviews > 1) and value.role != "adjudicator":
                item.status = "adjudication"
                await session.commit()
                raise AgentRigError(
                    ErrorCode.PERMISSION_DENIED,
                    "an adjudicator is required for disagreement or multi-review items",
                )
            if value.status == "resolved" and value.label is None:
                raise AgentRigError(ErrorCode.VALIDATION_ERROR, "resolved label is required")
            resolution_method = (
                "disputed"
                if value.status == "disputed"
                else "consensus"
                if not disputed and value.label in labels
                else "adjudication"
            )
            revision = int(
                await session.scalar(
                    select(func.max(GoldLabelORM.revision)).where(
                        GoldLabelORM.review_item_id == review_item_id
                    )
                )
                or 0
            ) + 1
            stable = {
                "schema_version": "agentrig.gold-label.v1",
                "project_id": project_id,
                "review_item_id": review_item_id,
                "revision": revision,
                "label": value.label if value.status == "resolved" else None,
                "source_annotation_ids": [row.id for row in current],
                "resolution_method": resolution_method,
                "adjudicator_id": value.adjudicator_id,
                "rationale_summary": value.rationale_summary,
                "status": value.status,
            }
            row = GoldLabelORM(
                id=new_id("gold"),
                project_id=project_id,
                review_item_id=review_item_id,
                revision=revision,
                label=value.label or "inconclusive",
                annotation_ids=stable["source_annotation_ids"],
                resolution_method=resolution_method,
                adjudicator_id=value.adjudicator_id,
                rationale=value.rationale_summary,
                status=value.status,
                schema_version="agentrig.gold-label.v1",
                content_hash=canonical_hash(stable),
            )
            session.add(row)
            item.status = "resolved" if value.status == "resolved" else "adjudication"
            item.resolved_at = utc_now() if value.status == "resolved" else None
            self._audit(
                session,
                project_id,
                "review_item",
                review_item_id,
                "gold_label_created",
                value.adjudicator_id,
                {"gold_label_id": row.id, "status": value.status},
            )
            await session.commit()
            await session.refresh(row)
        return self._gold_view(row)

    async def create_evaluator_version(
        self, project_id: str, value: EvaluatorVersionCreate
    ) -> EvaluatorVersionView:
        config = value.model_dump(mode="json", exclude={"created_by"})
        content_hash = canonical_hash(config)
        row = EvaluatorVersionORM(
            id=new_id("evalver"),
            project_id=project_id,
            evaluator_id=value.evaluator_id,
            version=value.semantic_version,
            evaluator_kind=value.evaluator_kind,
            name=value.name,
            status="draft",
            config_snapshot=config,
            content_hash=content_hash,
            created_by=value.created_by,
        )
        async with self._database.session() as session:
            session.add(row)
            self._audit(
                session,
                project_id,
                "evaluator_version",
                row.id,
                "draft_created",
                value.created_by,
                {"content_hash": content_hash},
            )
            try:
                await session.commit()
            except Exception as exc:
                raise AgentRigError(
                    ErrorCode.CONFLICT, "evaluator semantic version already exists"
                ) from exc
            await session.refresh(row)
        return self._evaluator_view(row)

    async def list_evaluator_versions(
        self, project_id: str, evaluator_id: str | None = None
    ) -> list[EvaluatorVersionView]:
        filters: list[Any] = [EvaluatorVersionORM.project_id == project_id]
        if evaluator_id:
            filters.append(EvaluatorVersionORM.evaluator_id == evaluator_id)
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(EvaluatorVersionORM)
                    .where(*filters)
                    .order_by(EvaluatorVersionORM.created_at, EvaluatorVersionORM.id)
                )
            )
        return [self._evaluator_view(row) for row in rows]

    async def run_alignment(
        self,
        project_id: str,
        evaluator_version_id: str,
        value: AlignmentRunCreate,
    ) -> AlignmentReport:
        async with self._database.session() as session:
            evaluator = await session.scalar(
                select(EvaluatorVersionORM).where(
                    EvaluatorVersionORM.id == evaluator_version_id,
                    EvaluatorVersionORM.project_id == project_id,
                )
            )
            if evaluator is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "evaluator version not found")
            gold_rows = list(
                await session.scalars(
                    select(GoldLabelORM).where(
                        GoldLabelORM.project_id == project_id,
                        GoldLabelORM.id.in_(value.gold_label_ids),
                    )
                )
            )
            if len(gold_rows) != len(value.gold_label_ids):
                raise AgentRigError(ErrorCode.NOT_FOUND, "one or more gold labels not found")
            review_rows = list(
                await session.scalars(
                    select(ReviewItemORM).where(
                        ReviewItemORM.project_id == project_id,
                        ReviewItemORM.id.in_([row.review_item_id for row in gold_rows]),
                    )
                )
            )
            review_by_id = {row.id: row for row in review_rows}
            prediction_by_id = {item.gold_label_id: item for item in value.predictions}
            unknown = set(prediction_by_id) - set(value.gold_label_ids)
            if unknown:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "predictions reference labels outside the frozen snapshot",
                    details={"gold_label_ids": sorted(unknown)},
                )
            metrics, disagreements, missing = self._metrics(gold_rows, prediction_by_id)
            cohort_sets: dict[str, list[GoldLabelORM]] = defaultdict(list)
            for gold in gold_rows:
                review = review_by_id.get(gold.review_item_id)
                if review:
                    cohort_sets[f"source:{review.subject_type}"].append(gold)
                    if review.cohort:
                        cohort_sets[f"cohort:{review.cohort}"].append(gold)
                prediction = prediction_by_id.get(gold.id)
                if prediction:
                    for key, cohort_value in sorted(prediction.cohorts.items()):
                        cohort_sets[f"{key}:{cohort_value}"].append(gold)
            cohort_metrics = {
                key: self._metrics(rows, prediction_by_id)[0].model_dump(mode="json")
                for key, rows in sorted(cohort_sets.items())
            }
            snapshot = {
                "evaluator_version_id": evaluator.id,
                "evaluator_content_hash": evaluator.content_hash,
                "gold_labels": sorted(
                    ({"id": row.id, "content_hash": row.content_hash} for row in gold_rows),
                    key=lambda item: item["id"],
                ),
            }
            now = utc_now()
            row = AlignmentRunORM(
                id=new_id("align"),
                project_id=project_id,
                evaluator_version_id=evaluator.id,
                gold_label_ids=value.gold_label_ids,
                predictions=[item.model_dump(mode="json") for item in value.predictions],
                status="completed",
                metrics=metrics.model_dump(mode="json"),
                cohort_metrics=cohort_metrics,
                disagreements=disagreements,
                source_snapshot_hash=canonical_hash(snapshot),
                limitations=[
                    "disputed_gold_labels_excluded_from_blocking_denominator"
                ],
                finished_at=now,
            )
            session.add(row)
            self._audit(
                session,
                project_id,
                "evaluator_version",
                evaluator.id,
                "alignment_completed",
                evaluator.created_by,
                {"alignment_run_id": row.id, "source_snapshot_hash": row.source_snapshot_hash},
            )
            await session.commit()
            await session.refresh(row)
        return self._alignment_report(row, missing)

    async def get_alignment_report(
        self, project_id: str, alignment_run_id: str
    ) -> AlignmentReport:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AlignmentRunORM).where(
                    AlignmentRunORM.id == alignment_run_id,
                    AlignmentRunORM.project_id == project_id,
                )
            )
        if row is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "alignment run not found")
        missing = [
            item["gold_label_id"]
            for item in row.disagreements
            if item.get("kind") == "missing"
        ]
        return self._alignment_report(row, missing)

    async def activate_evaluator(
        self,
        project_id: str,
        evaluator_version_id: str,
        value: EvaluatorActivate,
    ) -> EvaluatorVersionView:
        async with self._database.session() as session:
            evaluator = await session.scalar(
                select(EvaluatorVersionORM).where(
                    EvaluatorVersionORM.id == evaluator_version_id,
                    EvaluatorVersionORM.project_id == project_id,
                )
            )
            if evaluator is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "evaluator version not found")
            if evaluator.status != "draft":
                raise AgentRigError(ErrorCode.CONFLICT, "only draft evaluators can be activated")
            if evaluator.created_by == value.approved_by:
                raise AgentRigError(
                    ErrorCode.PERMISSION_DENIED,
                    "evaluator author cannot be the sole approver",
                )
            alignment = await session.scalar(
                select(AlignmentRunORM).where(
                    AlignmentRunORM.id == value.alignment_run_id,
                    AlignmentRunORM.project_id == project_id,
                    AlignmentRunORM.evaluator_version_id == evaluator.id,
                    AlignmentRunORM.status == "completed",
                )
            )
            if alignment is None:
                raise AgentRigError(ErrorCode.NOT_FOUND, "completed alignment run not found")
            metrics = AlignmentMetrics.model_validate(alignment.metrics)
            if metrics.eligible_gold == 0 or metrics.coverage < 1:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "alignment must cover every eligible gold label before activation",
                )
            critical = [
                AlignmentMetrics.model_validate(item)
                for key, item in alignment.cohort_metrics.items()
                if key in {"risk:critical", "severity:critical"}
            ]
            if any(item.false_pass_rate > 0 for item in critical):
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "critical cohort contains a false pass",
                )
            old_active = list(
                await session.scalars(
                    select(EvaluatorVersionORM).where(
                        EvaluatorVersionORM.project_id == project_id,
                        EvaluatorVersionORM.evaluator_id == evaluator.evaluator_id,
                        EvaluatorVersionORM.status == "active",
                    )
                )
            )
            for old in old_active:
                old.status = "retired"
            evaluator.status = "active"
            evaluator.approved_by = value.approved_by
            evaluator.alignment_run_id = alignment.id
            evaluator.activated_at = utc_now()
            self._audit(
                session,
                project_id,
                "evaluator_version",
                evaluator.id,
                "activated",
                value.approved_by,
                {"alignment_run_id": alignment.id},
            )
            await session.commit()
            await session.refresh(evaluator)
        return self._evaluator_view(evaluator)

    async def _subject_snapshot_hash(
        self, project_id: str, subject_kind: str, subject_id: str
    ) -> str:
        async with self._database.session() as session:
            if subject_kind == "case_run":
                row = await session.scalar(
                    select(CaseRunORM).where(
                        CaseRunORM.id == subject_id, CaseRunORM.project_id == project_id
                    )
                )
                if row:
                    return canonical_hash(
                        {
                            "id": row.id,
                            "status": row.status,
                            "evaluation_state": row.evaluation_state,
                            "case_snapshot": row.case_snapshot,
                            "target_snapshot": row.target_snapshot,
                            "profile_snapshot": row.profile_snapshot,
                            "capability_snapshot": row.capability_snapshot,
                            "summary": row.summary,
                        }
                    )
            elif subject_kind == "production_trace":
                row = await session.scalar(
                    select(ProductionTraceORM).where(
                        ProductionTraceORM.id == subject_id,
                        ProductionTraceORM.project_id == project_id,
                    )
                )
                if row:
                    return str(row.content_hash)
            else:
                row = await session.scalar(
                    select(ProductionSpanORM).where(
                        ProductionSpanORM.id == subject_id,
                        ProductionSpanORM.project_id == project_id,
                    )
                )
                if row:
                    return str(row.content_hash)
        raise AgentRigError(ErrorCode.NOT_FOUND, "review subject not found")

    async def _review_row(
        self, session: Any, project_id: str, review_item_id: str
    ) -> ReviewItemORM:
        row = await session.scalar(
            select(ReviewItemORM).where(
                ReviewItemORM.id == review_item_id,
                ReviewItemORM.project_id == project_id,
            )
        )
        if row is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, "review item not found")
        return cast(ReviewItemORM, row)

    async def _validate_evidence_refs(
        self,
        session: Any,
        project_id: str,
        item: ReviewItemORM,
        refs: list[str],
    ) -> None:
        for ref in refs:
            kind, separator, identifier = ref.partition(":")
            if not separator:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "evidence refs must use kind:id notation",
                    details={"evidence_ref": ref},
                )
            found = False
            if kind == "case_run":
                found = (
                    await session.scalar(
                        select(CaseRunORM.id).where(
                            CaseRunORM.id == identifier,
                            CaseRunORM.project_id == project_id,
                        )
                    )
                    is not None
                )
            elif kind == "event":
                found = (
                    await session.scalar(
                        select(RunEventORM.id)
                        .join(CaseRunORM, CaseRunORM.id == RunEventORM.case_run_id)
                        .where(
                            RunEventORM.id == identifier,
                            CaseRunORM.project_id == project_id,
                        )
                    )
                    is not None
                )
            elif kind == "trace":
                found = (
                    await session.scalar(
                        select(ProductionTraceORM.id).where(
                            ProductionTraceORM.id == identifier,
                            ProductionTraceORM.project_id == project_id,
                        )
                    )
                    is not None
                )
            elif kind == "span":
                found = (
                    await session.scalar(
                        select(ProductionSpanORM.id).where(
                            ProductionSpanORM.id == identifier,
                            ProductionSpanORM.project_id == project_id,
                        )
                    )
                    is not None
                )
            if not found:
                raise AgentRigError(
                    ErrorCode.NOT_FOUND,
                    "annotation evidence ref not found in project",
                    details={"evidence_ref": ref},
                )
        direct = f"{item.subject_type}:{item.subject_id}"
        if direct not in refs and not any(ref.startswith(("event:", "span:")) for ref in refs):
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "annotation evidence must be owned by the review subject",
            )

    @staticmethod
    def _current_annotations(rows: list[AnnotationORM]) -> list[AnnotationORM]:
        superseded = {row.supersedes_id for row in rows if row.supersedes_id}
        current = [row for row in rows if row.id not in superseded]
        latest_by_annotator: dict[str, AnnotationORM] = {}
        for row in current:
            latest_by_annotator[row.annotator_id] = row
        return sorted(latest_by_annotator.values(), key=lambda row: row.revision)

    @staticmethod
    def _metrics(
        gold_rows: list[GoldLabelORM],
        predictions: dict[str, AlignmentPrediction],
    ) -> tuple[AlignmentMetrics, list[dict[str, Any]], list[str]]:
        matrix = {gold: {pred: 0 for pred in _LABELS} for gold in _LABELS}
        eligible = [row for row in gold_rows if row.status == "resolved"]
        disputed = len(gold_rows) - len(eligible)
        missing: list[str] = []
        disagreements: list[dict[str, Any]] = []
        matched = 0
        for gold in eligible:
            prediction = predictions.get(gold.id)
            if prediction is None:
                missing.append(gold.id)
                disagreements.append({"kind": "missing", "gold_label_id": gold.id})
                continue
            matrix[gold.label][prediction.predicted_label] += 1
            if gold.label == prediction.predicted_label:
                matched += 1
            else:
                disagreements.append(
                    {
                        "kind": "disagreement",
                        "gold_label_id": gold.id,
                        "gold_label": gold.label,
                        "predicted_label": prediction.predicted_label,
                        "evidence_refs": prediction.evidence_refs,
                    }
                )
        predicted = len(eligible) - len(missing)
        precision: dict[str, float | None] = {}
        recall: dict[str, float | None] = {}
        for label in _LABELS:
            true_positive = matrix[label][label]
            predicted_total = sum(matrix[gold][label] for gold in _LABELS)
            actual_total = sum(matrix[label].values())
            precision[label] = true_positive / predicted_total if predicted_total else None
            recall[label] = true_positive / actual_total if actual_total else None
        nonpass = sum(sum(matrix[label].values()) for label in _LABELS if label != "pass")
        false_passes = sum(matrix[label]["pass"] for label in _LABELS if label != "pass")
        gold_pass = sum(matrix["pass"].values())
        false_fails = matrix["pass"]["fail"]
        metrics = AlignmentMetrics(
            total_gold=len(gold_rows),
            eligible_gold=len(eligible),
            predicted=predicted,
            missing=len(missing),
            disputed=disputed,
            coverage=predicted / len(eligible) if eligible else 0,
            agreement=matched / predicted if predicted else 0,
            confusion_matrix=matrix,
            precision_by_label=precision,
            recall_by_label=recall,
            false_pass_rate=false_passes / nonpass if nonpass else 0,
            false_fail_rate=false_fails / gold_pass if gold_pass else 0,
            inconclusive_rate=(
                sum(matrix[label]["inconclusive"] for label in _LABELS) / predicted
                if predicted
                else 0
            ),
            evaluation_error_rate=(
                sum(matrix[label]["evaluation_error"] for label in _LABELS) / predicted
                if predicted
                else 0
            ),
        )
        return metrics, disagreements, missing

    @staticmethod
    def _audit(
        session: Any,
        project_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        session.add(
            GovernanceAuditEventORM(
                id=new_id("audit"),
                project_id=project_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                actor=actor,
                details=details,
            )
        )

    @staticmethod
    def _review_view(row: ReviewItemORM) -> ReviewItemView:
        return ReviewItemView(
            id=row.id,
            project_id=row.project_id,
            subject_kind=cast(Any, row.subject_type),
            subject_id=row.subject_id,
            subject_snapshot_hash=row.subject_snapshot_hash,
            queue=row.queue,
            priority=row.priority,
            assignment=row.assignment,
            cohort=row.cohort,
            status=cast(Any, row.status),
            required_reviews=row.required_reviews,
            created_reason=row.created_reason,
            created_by=row.created_by,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
        )

    @staticmethod
    def _annotation_view(row: AnnotationORM) -> AnnotationView:
        return AnnotationView(
            id=row.id,
            project_id=row.project_id,
            review_item_id=row.review_item_id,
            revision=row.revision,
            reviewer_id=row.annotator_id,
            label=cast(Any, row.label),
            criteria=[AnnotationCriterion.model_validate(item) for item in row.criteria],
            evidence_refs=row.evidence_refs,
            rationale_summary=row.rationale,
            confidence=cast(Any, row.confidence),
            status="submitted",
            supersedes=row.supersedes_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _gold_view(row: GoldLabelORM) -> GoldLabelView:
        return GoldLabelView(
            id=row.id,
            project_id=row.project_id,
            review_item_id=row.review_item_id,
            revision=row.revision,
            label=cast(ReviewLabel | None, row.label if row.status == "resolved" else None),
            source_annotation_ids=row.annotation_ids,
            resolution_method=cast(Any, row.resolution_method),
            adjudicator_id=row.adjudicator_id,
            rationale_summary=row.rationale,
            status=cast(Any, row.status),
            content_hash=row.content_hash,
            created_at=row.created_at,
        )

    @staticmethod
    def _evaluator_view(row: EvaluatorVersionORM) -> EvaluatorVersionView:
        return EvaluatorVersionView(
            id=row.id,
            project_id=row.project_id,
            evaluator_id=row.evaluator_id,
            evaluator_kind=cast(Any, row.evaluator_kind),
            name=row.name,
            semantic_version=row.version,
            status=cast(Any, row.status),
            config_snapshot=row.config_snapshot,
            content_hash=row.content_hash,
            created_by=row.created_by,
            approved_by=row.approved_by,
            alignment_run_id=row.alignment_run_id,
            created_at=row.created_at,
            activated_at=row.activated_at,
        )

    @staticmethod
    def _alignment_report(row: AlignmentRunORM, missing: list[str]) -> AlignmentReport:
        if row.finished_at is None:
            raise AgentRigError(ErrorCode.CONFLICT, "alignment run is not complete")
        return AlignmentReport(
            id=row.id,
            project_id=row.project_id,
            evaluator_version_id=row.evaluator_version_id,
            gold_label_ids=row.gold_label_ids,
            status="completed",
            metrics=AlignmentMetrics.model_validate(row.metrics),
            cohort_metrics={
                key: AlignmentMetrics.model_validate(value)
                for key, value in row.cohort_metrics.items()
            },
            disagreements=[
                item for item in row.disagreements if item.get("kind") != "missing"
            ],
            missing=missing,
            limitations=row.limitations,
            source_snapshot_hash=row.source_snapshot_hash,
            created_at=row.created_at,
            finished_at=row.finished_at,
        )
