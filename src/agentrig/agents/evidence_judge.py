"""Evidence Judge：根据冻结要求和脱敏证据给出语义判定。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..evaluations.models import EvaluationRecordStatus
from ..evaluations.schemas import EvaluationCriterion, EvaluationDraft, EvaluationResult
from ..infrastructure.secrets import SecretResolver
from ..profiles.schemas import ModelConfigRef
from ..runs.schemas import CaseRunDetail
from .model_client import ModelClient
from .schemas import JudgeOutput

PROMPT_VERSION = "evidence_judge.v1"


class EvidenceJudge:
    def __init__(self, client: ModelClient, secrets: SecretResolver) -> None:
        self._client = client
        self._secrets = secrets

    async def evaluate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
    ) -> EvaluationDraft:
        valid_event_ids = {event.id for event in detail.events}
        feedback: list[str] = []
        last_metadata: dict[str, Any] = {}
        for attempt in range(2):
            try:
                result, metadata = await self._generate(
                    detail,
                    rule_result=rule_result,
                    model_config=model_config,
                    timeout_seconds=timeout_seconds,
                    feedback=feedback,
                )
                last_metadata = metadata
                unknown = sorted(
                    {
                        ref
                        for ref in [
                            *result.evidence_refs,
                            *(ref for item in result.criteria for ref in item.evidence_refs),
                        ]
                        if ref not in valid_event_ids
                    }
                )
                if unknown:
                    raise ValueError(f"unknown evidence_refs: {unknown}")
                return EvaluationDraft(
                    verdict=result.verdict,
                    summary=result.summary,
                    criteria=[
                        EvaluationCriterion.model_validate(item.model_dump())
                        for item in result.criteria
                    ],
                    evidence_refs=result.evidence_refs,
                    config_snapshot={
                        "prompt_version": PROMPT_VERSION,
                        "rubric": self._rubric(detail.case_snapshot),
                        "attempts": attempt + 1,
                    },
                    model_metadata=metadata,
                )
            except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                feedback = [str(exc)]
            except Exception as exc:
                return EvaluationDraft(
                    status=EvaluationRecordStatus.ERROR,
                    verdict=None,
                    summary=f"Evidence Judge model request failed: {exc}",
                    config_snapshot={
                        "prompt_version": PROMPT_VERSION,
                        "attempts": attempt + 1,
                        "request_error": str(exc),
                    },
                    model_metadata=last_metadata,
                )
        return EvaluationDraft(
            status=EvaluationRecordStatus.ERROR,
            verdict=None,
            summary=f"Evidence Judge output validation failed: {'; '.join(feedback)}",
            config_snapshot={
                "prompt_version": PROMPT_VERSION,
                "attempts": 2,
                "validation_errors": feedback,
            },
            model_metadata=last_metadata,
        )

    async def _generate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        feedback: list[str],
    ) -> tuple[JudgeOutput, dict[str, Any]]:
        api_key = self._secrets.resolve(model_config.secret_ref)
        assert api_key is not None
        payload = {
            "case": detail.case_snapshot,
            "rubric": self._rubric(detail.case_snapshot),
            "events": [event.model_dump(mode="json") for event in detail.events],
            "rule_result": (
                rule_result.model_dump(mode="json") if rule_result is not None else None
            ),
            "execution": {
                "status": detail.status,
                "error_code": detail.error_code,
                "error_message": detail.error_message,
            },
            "validation_feedback": feedback,
        }
        output = await self._client.generate_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are AgentRig Evidence Judge. Evaluate only the supplied frozen case "
                        "requirements and evidence. Cite event IDs. Return pass, fail, or "
                        "inconclusive without a numeric score. Return JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            json_schema=JudgeOutput.model_json_schema(),
            base_url=model_config.base_url,
            model=model_config.model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            options=model_config.options,
        )
        return JudgeOutput.model_validate(output.value), output.metadata

    @staticmethod
    def _rubric(case_snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "case": case_snapshot.get("case_rubric"),
            "turns": [
                {
                    "turn_position": turn["position"],
                    "rubric": turn.get("rubric"),
                }
                for turn in case_snapshot.get("turns", [])
                if turn.get("rubric")
            ],
        }
