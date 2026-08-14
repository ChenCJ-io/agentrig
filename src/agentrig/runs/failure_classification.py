"""Machine-readable failure taxonomy shared by reports, UI, and recovery."""

from __future__ import annotations

from ..errors import ErrorCode
from ..evaluations.models import EvaluationOutcome
from .models import CaseRunStatus, FailureClass

_ERROR_CLASS: dict[str, FailureClass] = {
    ErrorCode.TARGET_UNREACHABLE.value: FailureClass.TARGET_UNREACHABLE,
    ErrorCode.DRIVER_CAPABILITY_MISSING.value: FailureClass.CONTRACT_INCOMPATIBLE,
    ErrorCode.VERSION_INCOMPATIBLE.value: FailureClass.CONTRACT_INCOMPATIBLE,
    ErrorCode.INVALID_EVALUATION_CONFIG.value: FailureClass.CONTRACT_INCOMPATIBLE,
    ErrorCode.VALIDATION_ERROR.value: FailureClass.CONTRACT_INCOMPATIBLE,
    ErrorCode.PROVIDER_EXHAUSTED.value: FailureClass.TOOL_RESULT_UNAVAILABLE,
    ErrorCode.TOOL_RESULT_INVALID.value: FailureClass.TOOL_RESULT_UNAVAILABLE,
    ErrorCode.CASE_TIMEOUT.value: FailureClass.TIMEOUT,
    ErrorCode.COMPONENT_TIMEOUT.value: FailureClass.TIMEOUT,
    ErrorCode.EVALUATION_ERROR.value: FailureClass.EVALUATION_ERROR,
    ErrorCode.PERMISSION_DENIED.value: FailureClass.POLICY_DENIED,
    ErrorCode.DECISION_DENIED.value: FailureClass.POLICY_DENIED,
    ErrorCode.CANCELLED.value: FailureClass.CANCELLED,
    ErrorCode.INTERRUPTED.value: FailureClass.INTERRUPTED,
    ErrorCode.INTERNAL_ERROR.value: FailureClass.INTERNAL_ERROR,
}


def classify_failure(
    *,
    error_code: str | None = None,
    evaluation_state: EvaluationOutcome | str | None = None,
    status: CaseRunStatus | str | None = None,
) -> FailureClass | None:
    if error_code:
        return _ERROR_CLASS.get(error_code, FailureClass.UNKNOWN)
    if evaluation_state is not None:
        outcome = (
            evaluation_state.value
            if isinstance(evaluation_state, EvaluationOutcome)
            else evaluation_state
        )
        if outcome == EvaluationOutcome.FAIL.value:
            return FailureClass.BEHAVIOR_REGRESSION
        if outcome == EvaluationOutcome.EVALUATION_ERROR.value:
            return FailureClass.EVALUATION_ERROR
    if status is not None:
        status_value = status.value if isinstance(status, CaseRunStatus) else status
        if status_value == CaseRunStatus.CANCELLED.value:
            return FailureClass.CANCELLED
        if status_value == CaseRunStatus.INTERRUPTED.value:
            return FailureClass.INTERRUPTED
        if status_value == CaseRunStatus.FAILED.value:
            return FailureClass.UNKNOWN
    return None
