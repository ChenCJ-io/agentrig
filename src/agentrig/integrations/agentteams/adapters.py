"""SimulationCuratorPort/EvidenceJudgePort 的 AgentTeams Worker 适配器。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from ...agents.invocation_coordinator import AgentInvocationCoordinator
from ...agents.invocation_models import AgentRole
from ...agents.invocation_schemas import AgentInvocationCreate
from ...agents.ports import AgentTaskContext
from ...agents.schemas import CuratorGeneration, CuratorInput, JudgeOutput
from ...errors import AgentRigError, ErrorCode
from ...evaluations.models import EvaluationRecordStatus
from ...evaluations.schemas import EvaluationCriterion, EvaluationDraft, EvaluationResult
from ...profiles.schemas import ModelConfigRef
from ...runs.schemas import CaseRunDetail


class AgentTeamsSimulationCurator:
    def __init__(self, coordinator: AgentInvocationCoordinator) -> None:
        self._coordinator = coordinator

    async def generate(
        self,
        value: CuratorInput,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentTaskContext | None = None,
    ) -> CuratorGeneration:
        if context is None:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "AgentTeams Curator requires a run context",
            )
        snapshot = {
            "kind": AgentRole.SIMULATION_CURATOR.value,
            "input": value.model_dump(mode="json"),
            "model_hint": model_config.model,
        }
        invocation = await self._coordinator.execute(
            AgentInvocationCreate(
                role=AgentRole.SIMULATION_CURATOR,
                context=context,
                input_snapshot=snapshot,
                attempt=max(1, len(value.validation_feedback) + 1),
                deadline=datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds),
                idempotency_key=self._key(AgentRole.SIMULATION_CURATOR, context, snapshot),
            )
        )
        try:
            generation = CuratorGeneration.model_validate(invocation.result_payload)
        except ValidationError as exc:
            raise AgentRigError(
                ErrorCode.AGENT_RESULT_INVALID,
                f"Curator Worker returned an invalid result: {exc}",
                details={"invocation_id": invocation.id},
            ) from exc
        return generation.model_copy(
            update={
                "model_metadata": {
                    **generation.model_metadata,
                    "agent_invocation_id": invocation.id,
                    "assigned_agent": invocation.assigned_agent,
                }
            }
        )

    @staticmethod
    def _key(
        role: AgentRole,
        context: AgentTaskContext,
        snapshot: dict[str, Any],
    ) -> str:
        digest = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        return f"{role.value}:{context.case_run_id}:{context.tool_call_event_id}:{digest}"


class AgentTeamsEvidenceJudge:
    def __init__(self, coordinator: AgentInvocationCoordinator) -> None:
        self._coordinator = coordinator

    async def evaluate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentTaskContext | None = None,
    ) -> EvaluationDraft:
        if context is None:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "AgentTeams Judge requires a run context",
            )
        valid_event_ids = {event.id for event in detail.events}
        feedback: list[str] = []
        invocation_ids: list[str] = []
        last_assigned_agent: str | None = None
        for attempt in range(1, 3):
            snapshot = {
                "kind": AgentRole.EVIDENCE_JUDGE.value,
                "case": detail.case_snapshot,
                "events": [item.model_dump(mode="json") for item in detail.events],
                "rule_result": (
                    rule_result.model_dump(mode="json")
                    if rule_result is not None
                    else None
                ),
                "execution": {
                    "status": detail.status.value,
                    "error_code": detail.error_code,
                    "error_message": detail.error_message,
                },
                "validation_feedback": feedback,
                "model_hint": model_config.model,
            }
            key = AgentTeamsSimulationCurator._key(
                AgentRole.EVIDENCE_JUDGE,
                context,
                snapshot,
            )
            invocation = await self._coordinator.execute(
                AgentInvocationCreate(
                    role=AgentRole.EVIDENCE_JUDGE,
                    context=context,
                    input_snapshot=snapshot,
                    attempt=attempt,
                    deadline=datetime.now(timezone.utc)
                    + timedelta(seconds=timeout_seconds),
                    idempotency_key=key,
                )
            )
            invocation_ids.append(invocation.id)
            last_assigned_agent = invocation.assigned_agent
            try:
                output = JudgeOutput.model_validate(invocation.result_payload)
            except ValidationError as exc:
                feedback = [f"invalid result schema: {exc}"]
                continue
            referenced = {
                *output.evidence_refs,
                *(ref for item in output.criteria for ref in item.evidence_refs),
            }
            unknown = sorted(referenced - valid_event_ids)
            if unknown:
                feedback = [f"unknown evidence refs: {unknown}"]
                continue
            return EvaluationDraft(
                verdict=output.verdict,
                summary=output.summary,
                criteria=[
                    EvaluationCriterion.model_validate(item.model_dump())
                    for item in output.criteria
                ],
                evidence_refs=output.evidence_refs,
                config_snapshot={
                    "adapter": "agentteams",
                    "attempts": attempt,
                    "agent_invocation_ids": invocation_ids,
                },
                model_metadata={
                    "agent_invocation_id": invocation.id,
                    "agent_invocation_ids": invocation_ids,
                    "assigned_agent": invocation.assigned_agent,
                },
            )
        return EvaluationDraft(
            status=EvaluationRecordStatus.ERROR,
            summary=f"Evidence Judge output validation failed: {'; '.join(feedback)}",
            config_snapshot={
                "adapter": "agentteams",
                "attempts": 2,
                "validation_errors": feedback,
                "agent_invocation_ids": invocation_ids,
            },
            model_metadata={
                "agent_invocation_ids": invocation_ids,
                "assigned_agent": last_assigned_agent,
            },
        )
