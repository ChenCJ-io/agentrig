"""统一、append-only 的运行事件写入入口。"""

from __future__ import annotations

from typing import Any

from .models import RunEventType
from .redactor import Redactor
from .repository import RunRepository
from .schemas import RunEvent


class EventRecorder:
    def __init__(self, repository: RunRepository, redactor: Redactor) -> None:
        self._repository = repository
        self._redactor = redactor

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
        return await self._repository.append_event(case_run_id, event_type, safe_payload)
