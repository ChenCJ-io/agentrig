"""EvaluationPlan 状态机、预览、确认和幂等提交。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..profiles.models import ProviderName
from ..runs.schemas import RunCasesRequest, RunPreview, RunSubmitResult
from ..runs.service import RunService
from .models import ActorType, AssistantEventType, EvaluationPlanStatus
from .repository import AssistantRepository
from .schemas import (
    EvaluationPlanConfirm,
    EvaluationPlanCreate,
    EvaluationPlanPatch,
    EvaluationPlanSubmit,
    EvaluationPlanValidation,
    EvaluationPlanView,
)
from .service import AssistantService


class EvaluationPlanService:
    def __init__(
        self,
        *,
        repository: AssistantRepository,
        assistant: AssistantService,
        runs: RunService,
    ) -> None:
        self._repository = repository
        self._assistant = assistant
        self._runs = runs
        self._locks: dict[str, asyncio.Lock] = {}

    async def create(self, value: EvaluationPlanCreate) -> EvaluationPlanView:
        session = await self._assistant.get_session(value.session_id)
        turn = await self._assistant.get_turn(value.source_turn_id)
        if turn.session_id != value.session_id:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "source turn does not belong to the assistant session",
            )
        if value.parent_plan_id is not None:
            parent = await self.get(value.parent_plan_id)
            if parent.session_id != value.session_id:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "parent plan does not belong to the assistant session",
                )
        plan = await self._repository.create_plan(new_id("plan"), value)
        await self._assistant.append_event(
            session.id,
            AssistantEventType.PLAN_CREATED,
            actor_type=ActorType.MANAGER,
            actor_id=value.created_by,
            payload={"plan_id": plan.id, "revision": plan.revision},
            turn_id=value.source_turn_id,
            plan_id=plan.id,
        )
        validated = await self.validate(plan.id)
        return validated.plan

    async def get(self, plan_id: str) -> EvaluationPlanView:
        plan = await self._repository.get_plan(plan_id)
        if plan is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"evaluation plan not found: {plan_id}",
                details={"plan_id": plan_id},
            )
        return plan

    async def update(
        self,
        plan_id: str,
        value: EvaluationPlanPatch,
        *,
        actor_type: ActorType = ActorType.MANAGER,
        actor_id: str | None = None,
    ) -> EvaluationPlanView:
        plan = await self.get(plan_id)
        self._require_status(plan, EvaluationPlanStatus.DRAFT)
        updated = await self._repository.update_draft_plan(plan_id, value)
        assert updated is not None
        validated = await self.validate(plan_id)
        await self._assistant.append_event(
            plan.session_id,
            AssistantEventType.PLAN_UPDATED,
            actor_type=actor_type,
            actor_id=actor_id or plan.created_by,
            payload={"plan_id": plan_id, "revision": plan.revision},
            plan_id=plan_id,
        )
        return validated.plan

    async def validate(self, plan_id: str) -> EvaluationPlanValidation:
        plan = await self.get(plan_id)
        if plan.status in {
            EvaluationPlanStatus.SUBMITTED,
            EvaluationPlanStatus.CANCELLED,
        }:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"cannot validate a {plan.status.value} plan",
            )
        request = plan.run_request()
        preview = await self._runs.preview_run_cases(request)
        fingerprint = self._fingerprint(request, preview)
        if plan.status is EvaluationPlanStatus.DRAFT:
            reasons = self._confirmation_reasons(request, preview)
            plan = await self._repository.save_plan_preview(
                plan_id,
                preview=preview.model_dump(mode="json"),
                selection_hash=fingerprint,
                confirmation={"required": bool(reasons), "reasons": reasons},
            )
        return EvaluationPlanValidation(plan=plan, preview=preview)

    async def confirm(
        self,
        plan_id: str,
        value: EvaluationPlanConfirm,
    ) -> EvaluationPlanView:
        plan = await self.get(plan_id)
        self._require_status(plan, EvaluationPlanStatus.DRAFT)
        validated = await self.validate(plan_id)
        event = await self._assistant.get_event(value.confirmation_event_id)
        if (
            event.session_id != plan.session_id
            or event.actor_type is not ActorType.USER
            or event.event_type is not AssistantEventType.USER_MESSAGE
        ):
            raise AgentRigError(
                ErrorCode.PLAN_CONFIRMATION_REQUIRED,
                "confirmation must reference a user message in the same session",
                details={"confirmation_event_id": value.confirmation_event_id},
            )
        if event.actor_id != value.confirmed_by:
            raise AgentRigError(
                ErrorCode.PLAN_CONFIRMATION_REQUIRED,
                "confirmed_by must match the user who authored the confirmation event",
                details={"confirmation_event_id": value.confirmation_event_id},
            )
        confirmed = await self._repository.confirm_plan(
            plan_id,
            confirmation_event_id=value.confirmation_event_id,
            confirmed_by=value.confirmed_by,
        )
        await self._assistant.append_event(
            plan.session_id,
            AssistantEventType.PLAN_CONFIRMED,
            actor_type=ActorType.USER,
            actor_id=value.confirmed_by,
            payload={
                "plan_id": plan_id,
                "confirmation_required": validated.plan.confirmation.required,
            },
            plan_id=plan_id,
        )
        return confirmed

    async def cancel(self, plan_id: str) -> EvaluationPlanView:
        plan = await self.get(plan_id)
        if plan.status is EvaluationPlanStatus.SUBMITTED:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "a submitted plan cannot be cancelled; cancel its run instead",
                details={"run_id": plan.run_id},
            )
        if plan.status is EvaluationPlanStatus.CANCELLED:
            return plan
        return await self._repository.cancel_plan(plan_id)

    async def submit(
        self,
        plan_id: str,
        value: EvaluationPlanSubmit,
    ) -> tuple[EvaluationPlanView, RunSubmitResult]:
        lock = self._locks.setdefault(plan_id, asyncio.Lock())
        async with lock:
            plan = await self.get(plan_id)
            if plan.status is EvaluationPlanStatus.SUBMITTED:
                if plan.submit_idempotency_key != value.idempotency_key:
                    raise AgentRigError(
                        ErrorCode.PLAN_ALREADY_SUBMITTED,
                        "plan was already submitted with another idempotency key",
                        details={"plan_id": plan_id, "run_id": plan.run_id},
                    )
                assert plan.run_id is not None
                run = await self._runs.get_run(plan.run_id)
                return plan, RunSubmitResult(
                    run_id=run.id,
                    status=run.status,
                    resolved_case_ids=run.resolved_case_ids,
                    planned_case_runs=run.total_count - run.skipped_count,
                    skipped_items=[],
                )
            self._require_status(plan, EvaluationPlanStatus.CONFIRMED)
            request = plan.run_request()
            try:
                preview = await self._runs.preview_run_cases(request)
                current_hash = self._fingerprint(request, preview)
                if current_hash != plan.selection_hash:
                    raise AgentRigError(
                        ErrorCode.PLAN_STALE,
                        "confirmed plan no longer matches current assets",
                        details={"plan_id": plan_id},
                    )
                staged = await self._runs.stage_run_cases(request)
            except AgentRigError as exc:
                await self._repository.save_plan_error(
                    plan_id,
                    exc.detail.model_dump(mode="json"),
                )
                raise
            updated = await self._repository.mark_plan_submitted(
                plan_id,
                idempotency_key=value.idempotency_key,
                run_id=staged.response.run_id,
            )
            self._runs.start_staged_run(staged)
            submitted = staged.response
            await self._assistant.append_event(
                plan.session_id,
                AssistantEventType.PLAN_SUBMITTED,
                actor_type=ActorType.MANAGER,
                actor_id=plan.created_by,
                payload={"plan_id": plan_id, "run_id": submitted.run_id},
                plan_id=plan_id,
                run_id=submitted.run_id,
            )
            return updated, submitted

    @staticmethod
    def _confirmation_reasons(
        request: RunCasesRequest,
        preview: RunPreview,
    ) -> list[str]:
        reasons: list[str] = []
        if request.selector is not None:
            reasons.append("Manager selected cases by selector")
        if len(request.targets) == 2:
            reasons.append("A/B comparison")
        if (request.repeat_count or 1) > 1:
            reasons.append("repeated execution")
        providers = set(preview.providers)
        if ProviderName.REAL_TOOL.value in providers:
            reasons.append("real tool access")
        if preview.planned_case_runs > 20:
            reasons.append("large run")
        return reasons

    @staticmethod
    def _fingerprint(request: RunCasesRequest, preview: RunPreview) -> str:
        value: dict[str, Any] = {
            "selection": request.model_dump(mode="json"),
            "preview": preview.model_dump(mode="json"),
        }
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_status(
        plan: EvaluationPlanView,
        expected: EvaluationPlanStatus,
    ) -> None:
        if plan.status is not expected:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"plan must be {expected.value}, got {plan.status.value}",
                details={"plan_id": plan.id, "status": plan.status.value},
            )
