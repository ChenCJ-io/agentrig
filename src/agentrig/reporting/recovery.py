"""Recovery Run 到报告有效 Attempt 的纯函数投影。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..evaluations.models import EvaluationOutcome
from ..runs.models import CaseRunStatus
from .schemas import RecoveryProvenance

if TYPE_CHECKING:
    from ..runs.schemas import CaseRunDetail, RunView

_QUALITY_TERMINAL_OUTCOMES = {
    EvaluationOutcome.PASS,
    EvaluationOutcome.FAIL,
    EvaluationOutcome.INCONCLUSIVE,
}


@dataclass(frozen=True)
class RecoveryOverlay:
    effective_case_runs: tuple[CaseRunDetail, ...]
    recovery_runs: tuple[RunView, ...]
    provenance: RecoveryProvenance


def apply_recovery_overlay(
    source_run: RunView,
    source_case_runs: list[CaseRunDetail],
    recovery_runs: list[RunView],
    recovery_case_runs: list[CaseRunDetail],
) -> RecoveryOverlay:
    """用最新的高质量 Recovery Attempt 覆盖源 Attempt，但不改变源证据。"""

    ordered_runs = sorted(recovery_runs, key=lambda item: (item.created_at, item.id))
    run_rank = {item.id: index for index, item in enumerate(ordered_runs, start=1)}
    source_by_id = {item.id: item for item in source_case_runs}
    recovery_by_id = {item.id: item for item in recovery_case_runs}
    all_by_id = {**source_by_id, **recovery_by_id}

    winners: dict[str, CaseRunDetail] = {}
    for candidate in recovery_case_runs:
        root_id = _source_attempt_id(candidate, source_by_id, all_by_id)
        if root_id is None or not _is_quality_terminal(candidate):
            continue
        current = winners.get(root_id)
        if current is None or _candidate_key(candidate, run_rank) > _candidate_key(
            current,
            run_rank,
        ):
            winners[root_id] = candidate

    effective = [winners.get(item.id, item) for item in source_case_runs]
    applied_run_ids = sorted(
        {item.run_id for item in winners.values()},
        key=lambda item: (run_rank.get(item, 0), item),
    )
    provenance = RecoveryProvenance(
        source_run_id=source_run.id,
        recovery_run_ids=[item.id for item in ordered_runs],
        applied_recovery_run_ids=applied_run_ids,
        effective_attempt_count=len(effective),
        replaced_attempt_count=len(winners),
        superseded_attempt_ids=sorted(winners),
        effective_attempt_ids=[item.attempt_id or item.id for item in effective],
    )
    return RecoveryOverlay(
        effective_case_runs=tuple(effective),
        recovery_runs=tuple(ordered_runs),
        provenance=provenance,
    )


def _source_attempt_id(
    candidate: CaseRunDetail,
    source_by_id: dict[str, CaseRunDetail],
    all_by_id: dict[str, CaseRunDetail],
) -> str | None:
    parent_id = candidate.recovery_of_case_run_id
    visited = {candidate.id}
    while parent_id is not None and parent_id not in visited:
        if parent_id in source_by_id:
            return parent_id
        visited.add(parent_id)
        parent = all_by_id.get(parent_id)
        if parent is None:
            return None
        parent_id = parent.recovery_of_case_run_id
    return None


def _is_quality_terminal(candidate: CaseRunDetail) -> bool:
    return (
        candidate.status is CaseRunStatus.COMPLETED
        and candidate.evaluation_state in _QUALITY_TERMINAL_OUTCOMES
    )


def _candidate_key(
    candidate: CaseRunDetail,
    run_rank: dict[str, int],
) -> tuple[int, datetime, str]:
    return (
        run_rank.get(candidate.run_id, 0),
        candidate.finished_at or datetime.min.replace(tzinfo=timezone.utc),
        candidate.id,
    )
