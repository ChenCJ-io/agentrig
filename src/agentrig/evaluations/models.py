"""评判状态与结论。"""

from enum import StrEnum


class EvaluatorType(StrEnum):
    RULE = "rule"
    EVIDENCE_JUDGE = "evidence_judge"
    EXTERNAL_CONTROLLER = "external_controller"


class EvaluationOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    AWAITING_VERDICT = "awaiting_verdict"
    EVALUATION_ERROR = "evaluation_error"


class EvaluationRecordStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"
