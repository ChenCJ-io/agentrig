"""DecisionRecord 持久化端口。"""

from __future__ import annotations

from typing import Protocol

from .decision_models import DecisionKind, DecisionStatus
from .decision_schemas import DecisionRecordPage, DecisionRecordView, ManagerDecisionProposal


class DecisionRepository(Protocol):
    async def create(
        self,
        decision_id: str,
        value: ManagerDecisionProposal,
        *,
        ordinal: int,
        status: DecisionStatus,
        context_hash: str,
        policy_verdict: dict[str, object],
        action_idempotency_key: str,
    ) -> DecisionRecordView: ...

    async def get(self, decision_id: str) -> DecisionRecordView | None: ...

    async def get_by_idempotency_key(self, key: str) -> DecisionRecordView | None: ...

    async def next_ordinal(self, session_id: str, turn_id: str) -> int: ...

    async def list_for_session(
        self,
        session_id: str,
        *,
        status: DecisionStatus | None,
        decision_kind: DecisionKind | None,
        limit: int,
        offset: int,
    ) -> DecisionRecordPage: ...

    async def set_status(
        self,
        decision_id: str,
        status: DecisionStatus,
        *,
        confirmation_event_id: str | None = None,
        action_ref_type: str | None = None,
        action_ref_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> DecisionRecordView: ...
