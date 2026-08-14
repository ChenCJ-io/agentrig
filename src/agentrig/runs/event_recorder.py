"""统一、append-only 的运行事件写入入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .models import RunEventType
from .redactor import Redactor
from .repository import RunRepository
from .schemas import RunEvent

_execution_attempt_id: ContextVar[str | None] = ContextVar(
    "agentrig_execution_attempt_id", default=None
)
ExternalSideEffectListener = Callable[[str], Awaitable[None]]


@contextmanager
def execution_attempt(attempt_id: str) -> Iterator[None]:
    """Associate all evidence emitted in this context with a durable attempt."""

    token = _execution_attempt_id.set(attempt_id)
    try:
        yield
    finally:
        _execution_attempt_id.reset(token)


class EventRecorder:
    def __init__(
        self,
        repository: RunRepository,
        redactor: Redactor,
        *,
        external_side_effect_listener: ExternalSideEffectListener | None = None,
    ) -> None:
        self._repository = repository
        self._redactor = redactor
        self._external_side_effect_listener = external_side_effect_listener

    async def mark_external_side_effect(self) -> None:
        """Fence durable retries before a Real Tool request can leave AgentRig."""

        attempt_id = _execution_attempt_id.get()
        if attempt_id is not None and self._external_side_effect_listener is not None:
            await self._external_side_effect_listener(attempt_id)

    async def record(
        self,
        case_run_id: str,
        event_type: RunEventType,
        payload: dict[str, Any],
        *,
        extra_sensitive_paths: list[str] | None = None,
    ) -> RunEvent:
        safe_payload = self._redactor.redact(
            payload,
            extra_sensitive_paths=extra_sensitive_paths,
        )
        attempt_id = _execution_attempt_id.get()
        if attempt_id is None:
            # Keep compatibility with lightweight repositories that implement
            # the pre-durable append signature.
            return await self._repository.append_event(case_run_id, event_type, safe_payload)
        return await self._repository.append_event(
            case_run_id,
            event_type,
            safe_payload,
            attempt_id=attempt_id,
        )
