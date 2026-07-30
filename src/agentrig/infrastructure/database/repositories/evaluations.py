"""Rule、Evidence Judge 和外部判定的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import select

from ....evaluations.models import EvaluationRecordStatus, EvaluatorType
from ....evaluations.schemas import EvaluationCriterion, EvaluationResult
from ....identifiers import new_id
from ..orm import EvaluationORM, utc_now
from ..session import Database


class SqlEvaluationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert(
        self,
        *,
        case_run_id: str,
        evaluator_type: EvaluatorType,
        evaluator_source: str,
        status: EvaluationRecordStatus,
        verdict: str | None,
        summary: str,
        criteria: list[EvaluationCriterion],
        evidence_refs: list[str],
        config_snapshot: dict[str, object],
        model_metadata: dict[str, object],
    ) -> EvaluationResult:
        async with self._database.session() as session:
            row = await session.scalar(
                select(EvaluationORM).where(
                    EvaluationORM.case_run_id == case_run_id,
                    EvaluationORM.evaluator_type == evaluator_type.value,
                )
            )
            if row is None:
                row = EvaluationORM(
                    id=new_id("evaluation"),
                    case_run_id=case_run_id,
                    evaluator_type=evaluator_type.value,
                    evaluator_source=evaluator_source,
                    status=status.value,
                    verdict=verdict,
                    summary=summary,
                    criteria=[item.model_dump(mode="json") for item in criteria],
                    evidence_refs=evidence_refs,
                    config_snapshot=config_snapshot,
                    model_metadata=model_metadata,
                )
                session.add(row)
            else:
                row.evaluator_source = evaluator_source
                row.status = status.value
                row.verdict = verdict
                row.summary = summary
                row.criteria = [item.model_dump(mode="json") for item in criteria]
                row.evidence_refs = evidence_refs
                row.config_snapshot = config_snapshot
                row.model_metadata = model_metadata
                row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
            return self._view(row)

    async def list_for_case_run(self, case_run_id: str) -> list[EvaluationResult]:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(EvaluationORM)
                    .where(EvaluationORM.case_run_id == case_run_id)
                    .order_by(EvaluationORM.created_at, EvaluationORM.id)
                )
            )
        return [self._view(row) for row in rows]

    @staticmethod
    def _view(row: EvaluationORM) -> EvaluationResult:
        return EvaluationResult.model_validate(
            {
                "id": row.id,
                "case_run_id": row.case_run_id,
                "evaluator_type": row.evaluator_type,
                "evaluator_source": row.evaluator_source,
                "status": row.status,
                "verdict": row.verdict,
                "summary": row.summary,
                "criteria": row.criteria,
                "evidence_refs": row.evidence_refs,
                "config_snapshot": row.config_snapshot,
                "model_metadata": row.model_metadata,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
