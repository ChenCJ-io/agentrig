"""评判记录存储接口。"""

from __future__ import annotations

from typing import Any, Protocol

from .models import EvaluationRecordStatus, EvaluatorType
from .schemas import EvaluationCriterion, EvaluationResult


class EvaluationRepository(Protocol):
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
        config_snapshot: dict[str, Any],
        model_metadata: dict[str, Any],
    ) -> EvaluationResult: ...

    async def list_for_case_run(self, case_run_id: str) -> list[EvaluationResult]: ...
