"""DecisionRecord 应用服务：校验、授权、幂等和动作结果绑定。"""

from __future__ import annotations

import hashlib
import json

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..runs.redactor import Redactor
from .decision_models import (
    DecisionActionType,
    DecisionKind,
    DecisionStatus,
    PolicyVerdictType,
)
from .decision_policy import DecisionPolicyService
from .decision_repository import DecisionRepository
from .decision_schemas import (
    DecisionRecordPage,
    DecisionRecordView,
    ManagerDecisionProposal,
)
from .models import ActorType, AssistantEventType
from .repository import AssistantRepository
from .service import AssistantService


class DecisionService:
    _immediate_actions = {
        DecisionActionType.ASK_USER,
        DecisionActionType.NO_ACTION,
        DecisionActionType.REQUEST_PLAN_CONFIRMATION,
    }
    _allowed_evidence_kinds = {
        "test_case",
        "target",
        "execution_profile",
        "tool_sample",
        "assistant_event",
        "evaluation_plan",
        "run",
        "case_run",
        "run_event",
        "evaluation",
        "agent_invocation",
        "target_check",
        "runtime_health",
    }

    def __init__(
        self,
        repository: DecisionRepository,
        *,
        assistant_repository: AssistantRepository,
        assistant: AssistantService,
        policy: DecisionPolicyService | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self._repository = repository
        self._assistant_repository = assistant_repository
        self._assistant = assistant
        self._policy = policy or DecisionPolicyService()
        self._redactor = redactor or Redactor()

    async def record(self, value: ManagerDecisionProposal) -> DecisionRecordView:
        session = await self._assistant.get_session(value.session_id)
        turn = await self._assistant.get_turn(value.turn_id)
        if turn.session_id != session.id:
            raise AgentRigError(
                ErrorCode.DECISION_INVALID,
                "decision turn does not belong to the assistant session",
            )
        if value.parent_decision_id is not None:
            parent = await self.get(value.parent_decision_id)
            if parent.session_id != session.id:
                raise AgentRigError(
                    ErrorCode.DECISION_INVALID,
                    "parent decision does not belong to the assistant session",
                )
        await self._validate_evidence(value)
        safe_payload = value.model_dump(mode="json")
        safe_payload.update(
            {
                "objective": self._redact_text(value.objective),
                "observation_summary": self._redactor.redact(
                    value.observation_summary.model_dump(mode="json")
                ),
                "rationale_summary": self._redactor.redact(
                    value.rationale_summary.model_dump(mode="json")
                ),
                "selected_action": self._redactor.redact(
                    value.selected_action.model_dump(mode="json")
                ),
            }
        )
        safe = ManagerDecisionProposal.model_validate(safe_payload)
        idempotency_key = safe.idempotency_key or self._proposal_key(safe)
        existing = await self._repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.session_id != safe.session_id:
                raise AgentRigError(
                    ErrorCode.DECISION_INVALID,
                    "decision idempotency key is already owned by another session",
                )
            return existing
        verdict = self._policy.evaluate(safe)
        status = {
            PolicyVerdictType.ALLOW: DecisionStatus.AUTHORIZED,
            PolicyVerdictType.REQUIRE_CONFIRMATION: DecisionStatus.AWAITING_CONFIRMATION,
            PolicyVerdictType.DENY: DecisionStatus.DENIED,
            PolicyVerdictType.STALE: DecisionStatus.STALE,
        }[verdict.verdict]
        if (
            status is DecisionStatus.AUTHORIZED
            and safe.selected_action.action_type in self._immediate_actions
        ):
            status = DecisionStatus.SUCCEEDED
        ordinal = await self._repository.next_ordinal(safe.session_id, safe.turn_id)
        context_hash = self._context_hash(safe)
        decision = await self._repository.create(
            new_id("decision"),
            safe,
            ordinal=ordinal,
            status=status,
            context_hash=context_hash,
            policy_verdict=verdict.model_dump(mode="json"),
            action_idempotency_key=idempotency_key,
        )
        await self._assistant.append_event(
            session.id,
            AssistantEventType.DECISION_RECORDED,
            actor_type=ActorType.MANAGER,
            actor_id=safe.proposed_by,
            payload=self._event_payload(decision),
            turn_id=safe.turn_id,
            decision_id=decision.id,
        )
        return decision

    async def get(self, decision_id: str) -> DecisionRecordView:
        decision = await self._repository.get(decision_id)
        if decision is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"decision not found: {decision_id}",
                details={"decision_id": decision_id},
            )
        return decision

    async def list_for_session(
        self,
        session_id: str,
        *,
        status: DecisionStatus | None = None,
        decision_kind: DecisionKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DecisionRecordPage:
        await self._assistant.get_session(session_id)
        return await self._repository.list_for_session(
            session_id,
            status=status,
            decision_kind=decision_kind,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def context(self, session_id: str) -> dict[str, object]:
        context = await self._assistant.get_context(session_id)
        decisions = await self.list_for_session(session_id, limit=20)
        return {
            **context,
            "recent_decisions": [item.model_dump(mode="json") for item in decisions.items],
            "decision_contract": {
                "schema_version": "agentrig.manager-decision.v1",
                "allowed_actions": [item.value for item in DecisionActionType],
                "policy_rule_version": "agentrig.decision-policy.v1",
            },
        }

    async def list_for_run(self, run_id: str) -> DecisionRecordPage:
        plan = await self._assistant_repository.get_plan_by_run_id(run_id)
        if plan is None:
            return DecisionRecordPage(items=[], total=0, limit=200, offset=0)
        page = await self.list_for_session(plan.session_id, limit=200)
        related_ids = {run_id, plan.id}
        items = [
            item
            for item in page.items
            if item.action_ref_id in related_ids
            or any(
                ref.resource_id in related_ids
                and ref.kind in {"run", "evaluation_plan"}
                for ref in item.evidence_refs
            )
        ]
        return DecisionRecordPage(
            items=items,
            total=len(items),
            limit=200,
            offset=0,
        )

    async def authorize(
        self,
        decision_id: str,
        confirmation_event_id: str,
    ) -> DecisionRecordView:
        decision = await self.get(decision_id)
        if decision.status is DecisionStatus.AUTHORIZED:
            return decision
        if decision.status is not DecisionStatus.AWAITING_CONFIRMATION:
            self._raise_status_conflict(decision)
        event = await self._assistant.get_event(confirmation_event_id)
        if (
            event.session_id != decision.session_id
            or event.actor_type is not ActorType.USER
            or event.event_type is not AssistantEventType.USER_MESSAGE
        ):
            raise AgentRigError(
                ErrorCode.DECISION_CONFIRMATION_REQUIRED,
                "decision confirmation must reference a user message in the same session",
            )
        updated = await self._repository.set_status(
            decision_id,
            DecisionStatus.AUTHORIZED,
            confirmation_event_id=confirmation_event_id,
        )
        await self._status_event(updated)
        return updated

    async def begin_action(
        self,
        decision_id: str,
        expected_action: DecisionActionType,
    ) -> DecisionRecordView:
        decision = await self.get(decision_id)
        if decision.selected_action.action_type is not expected_action:
            raise AgentRigError(
                ErrorCode.DECISION_ACTION_MISMATCH,
                "decision does not authorize this domain action",
                details={
                    "expected": expected_action.value,
                    "actual": decision.selected_action.action_type.value,
                },
            )
        if decision.status is DecisionStatus.EXECUTING:
            return decision
        if decision.status is DecisionStatus.SUCCEEDED:
            return decision
        if decision.status is not DecisionStatus.AUTHORIZED:
            if decision.status is DecisionStatus.AWAITING_CONFIRMATION:
                raise AgentRigError(
                    ErrorCode.DECISION_CONFIRMATION_REQUIRED,
                    "decision requires a real user confirmation",
                )
            self._raise_status_conflict(decision)
        updated = await self._repository.set_status(decision_id, DecisionStatus.EXECUTING)
        await self._status_event(updated)
        return updated

    async def complete_action(
        self,
        decision_id: str,
        *,
        action_ref_type: str,
        action_ref_id: str,
    ) -> DecisionRecordView:
        decision = await self.get(decision_id)
        if decision.status is DecisionStatus.SUCCEEDED:
            if (
                decision.action_ref_type == action_ref_type
                and decision.action_ref_id == action_ref_id
            ):
                return decision
            self._raise_status_conflict(decision)
        if decision.status is not DecisionStatus.EXECUTING:
            self._raise_status_conflict(decision)
        updated = await self._repository.set_status(
            decision_id,
            DecisionStatus.SUCCEEDED,
            action_ref_type=action_ref_type,
            action_ref_id=action_ref_id,
        )
        await self._status_event(updated)
        return updated

    async def fail_action(
        self,
        decision_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> DecisionRecordView:
        decision = await self.get(decision_id)
        if decision.status.terminal:
            return decision
        updated = await self._repository.set_status(
            decision_id,
            DecisionStatus.FAILED,
            error_code=error_code,
            error_message=self._redact_text(error_message)[:2_000],
        )
        await self._status_event(updated)
        return updated

    async def cancel(self, decision_id: str, reason: str) -> DecisionRecordView:
        decision = await self.get(decision_id)
        if decision.status is DecisionStatus.CANCELLED:
            return decision
        if decision.status.terminal:
            self._raise_status_conflict(decision)
        updated = await self._repository.set_status(
            decision_id,
            DecisionStatus.CANCELLED,
            error_message=self._redact_text(reason)[:500],
        )
        await self._status_event(updated)
        return updated

    async def _validate_evidence(self, value: ManagerDecisionProposal) -> None:
        for ref in value.evidence_refs:
            if ref.kind not in self._allowed_evidence_kinds:
                raise AgentRigError(
                    ErrorCode.DECISION_INVALID,
                    f"unsupported evidence kind: {ref.kind}",
                )
            if ref.kind == "assistant_event":
                event = await self._assistant.get_event(ref.resource_id)
                if event.session_id != value.session_id:
                    raise AgentRigError(
                        ErrorCode.DECISION_INVALID,
                        "assistant evidence belongs to another session",
                    )
            elif ref.kind == "evaluation_plan":
                plan = await self._assistant_repository.get_plan(ref.resource_id)
                if plan is None or plan.session_id != value.session_id:
                    raise AgentRigError(
                        ErrorCode.DECISION_INVALID,
                        "plan evidence does not belong to this session",
                    )
            elif ref.kind == "run":
                plan = await self._assistant_repository.get_plan_by_run_id(ref.resource_id)
                if plan is None or plan.session_id != value.session_id:
                    raise AgentRigError(
                        ErrorCode.DECISION_INVALID,
                        "run evidence does not belong to this session",
                    )

    async def _status_event(self, decision: DecisionRecordView) -> None:
        await self._assistant.append_event(
            decision.session_id,
            AssistantEventType.DECISION_STATUS_CHANGED,
            actor_type=ActorType.SYSTEM,
            actor_id="agentrig.decision-policy",
            payload=self._event_payload(decision),
            turn_id=decision.turn_id,
            decision_id=decision.id,
        )

    @staticmethod
    def _event_payload(decision: DecisionRecordView) -> dict[str, object]:
        return {
            "decision_id": decision.id,
            "decision_kind": decision.decision_kind.value,
            "status": decision.status.value,
            "action_type": decision.selected_action.action_type.value,
            "objective": decision.objective,
            "action_ref_type": decision.action_ref_type,
            "action_ref_id": decision.action_ref_id,
        }

    @staticmethod
    def _proposal_key(value: ManagerDecisionProposal) -> str:
        payload = {
            "session_id": value.session_id,
            "turn_id": value.turn_id,
            "decision_kind": value.decision_kind.value,
            "selected_action": value.selected_action.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"decision:{hashlib.sha256(encoded.encode()).hexdigest()}"

    def _redact_text(self, value: str) -> str:
        return str(self._redactor.redact({"value": value})["value"])

    @staticmethod
    def _context_hash(value: ManagerDecisionProposal) -> str:
        payload = {
            "session_id": value.session_id,
            "turn_id": value.turn_id,
            "evidence_refs": sorted(
                [item.model_dump(mode="json") for item in value.evidence_refs],
                key=lambda item: (
                    str(item["kind"]),
                    str(item["resource_id"]),
                    str(item.get("version") or ""),
                ),
            ),
            "selected_action": value.selected_action.model_dump(mode="json"),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    @staticmethod
    def _raise_status_conflict(decision: DecisionRecordView) -> None:
        raise AgentRigError(
            ErrorCode.CONFLICT,
            f"decision cannot transition from {decision.status.value}",
            details={"decision_id": decision.id, "status": decision.status.value},
        )
