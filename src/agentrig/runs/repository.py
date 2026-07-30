"""运行规划、事件和状态的持久化接口。"""

from __future__ import annotations

from typing import Any, Protocol

from ..evaluations.models import EvaluationOutcome, EvaluatorType
from .models import CaseRunStatus, RunEventType, RunStatus
from .schemas import CaseRunDetail, CaseRunPage, RunEvent, RunPage, RunView


class RunRepository(Protocol):
    async def create_run(
        self,
        *,
        run_id: str,
        selection_snapshot: dict[str, Any],
        resolved_case_ids: list[str],
        profile_snapshot: dict[str, Any],
        target_snapshots: list[dict[str, Any]],
    ) -> RunView: ...

    async def create_case_run(
        self,
        *,
        case_run_id: str,
        run_id: str,
        case_id: str,
        case_snapshot: dict[str, Any],
        target_snapshot: dict[str, Any],
        profile_snapshot: dict[str, Any],
        version: str | None,
        repeat_index: int,
        comparison_pair_id: str | None,
        comparison_role: str | None,
        status: CaseRunStatus,
        primary_evaluator: EvaluatorType,
        evaluation_state: EvaluationOutcome,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def get_run(self, run_id: str) -> RunView | None: ...

    async def list_runs(self, *, limit: int, offset: int) -> RunPage: ...

    async def list_case_runs(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> CaseRunPage: ...

    async def get_case_run(self, case_run_id: str) -> CaseRunDetail | None: ...

    async def set_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    async def set_case_run_status(
        self,
        case_run_id: str,
        status: CaseRunStatus,
        *,
        evaluation_state: EvaluationOutcome | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None: ...

    async def append_event(
        self,
        case_run_id: str,
        event_type: RunEventType,
        payload: dict[str, Any],
    ) -> RunEvent: ...

    async def set_evaluation_state(
        self,
        case_run_id: str,
        evaluation_state: EvaluationOutcome,
    ) -> None: ...

    async def mark_in_progress_interrupted(self) -> None: ...

    async def refresh_run_counts(self, run_id: str) -> RunView: ...
