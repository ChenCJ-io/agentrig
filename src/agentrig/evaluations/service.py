"""评判记录写入和当前主结论解析。"""

from __future__ import annotations

from ..errors import AgentRigError, ErrorCode
from ..runs.models import CaseRunStatus
from ..runs.repository import RunRepository
from .models import EvaluationOutcome, EvaluationRecordStatus, EvaluatorType
from .repository import EvaluationRepository
from .schemas import EvaluationResult, ExternalVerdictSubmit


class EvaluationService:
    def __init__(
        self,
        evaluations: EvaluationRepository,
        runs: RunRepository,
    ) -> None:
        self._evaluations = evaluations
        self._runs = runs

    async def submit_external_verdict(
        self,
        case_run_id: str,
        value: ExternalVerdictSubmit,
    ) -> EvaluationResult:
        detail = await self._runs.get_case_run(case_run_id)
        if detail is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"case run not found: {case_run_id}",
                details={"case_run_id": case_run_id},
            )
        if detail.status in {CaseRunStatus.QUEUED, CaseRunStatus.RUNNING}:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "external verdict can only be submitted after execution stops",
                details={"case_run_id": case_run_id, "status": detail.status},
            )
        valid_event_ids = {event.id for event in detail.events}
        unknown = sorted(set(value.evidence_refs) - valid_event_ids)
        if unknown:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "external verdict contains unknown evidence refs",
                details={"unknown_evidence_refs": unknown},
            )
        result = await self._evaluations.upsert(
            case_run_id=case_run_id,
            evaluator_type=EvaluatorType.EXTERNAL_CONTROLLER,
            evaluator_source=value.submitted_by,
            status=EvaluationRecordStatus.COMPLETED,
            verdict=value.verdict,
            summary=value.summary,
            criteria=[],
            evidence_refs=value.evidence_refs,
            config_snapshot={},
            model_metadata={},
        )
        await self._runs.set_evaluation_state(
            case_run_id,
            EvaluationOutcome(value.verdict),
        )
        return result
