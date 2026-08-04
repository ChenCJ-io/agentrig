"""V2.1 自适应决策的稳定枚举与状态语义。"""

from enum import StrEnum


class DecisionTrigger(StrEnum):
    USER_REQUEST = "user_request"
    USER_CONFIRMATION = "user_confirmation"
    PLAN_VALIDATION = "plan_validation"
    RUN_PROGRESS = "run_progress"
    RUN_TERMINAL = "run_terminal"
    INVOCATION_FAILED = "invocation_failed"
    EVIDENCE_INCONCLUSIVE = "evidence_inconclusive"
    ASSET_CHANGED = "asset_changed"
    OPERATOR_REQUEST = "operator_request"


class DecisionKind(StrEnum):
    CLARIFICATION = "clarification"
    SCOPE_SELECTION = "scope_selection"
    EXECUTION_STRATEGY = "execution_strategy"
    SUBMISSION = "submission"
    DIAGNOSIS = "diagnosis"
    RECOVERY = "recovery"
    ASSET_DRAFT = "asset_draft"


class DecisionActionType(StrEnum):
    ASK_USER = "ask_user"
    NO_ACTION = "no_action"
    CREATE_PLAN = "create_plan"
    CREATE_PLAN_REVISION = "create_plan_revision"
    UPDATE_DRAFT_PLAN = "update_draft_plan"
    REQUEST_PLAN_CONFIRMATION = "request_plan_confirmation"
    CONFIRM_PLAN = "confirm_plan"
    SUBMIT_PLAN = "submit_plan"
    CANCEL_PLAN = "cancel_plan"
    CANCEL_RUN = "cancel_run"
    RETRY_INVOCATION_DELIVERY = "retry_invocation_delivery"
    REQUEST_WORKER_CORRECTION = "request_worker_correction"
    CREATE_CASE_DRAFT = "create_case_draft"
    CREATE_SAMPLE_DRAFT = "create_sample_draft"
    CREATE_TARGET_DRAFT = "create_target_draft"


class DecisionStatus(StrEnum):
    PROPOSED = "proposed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    STALE = "stale"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            self.SUCCEEDED,
            self.FAILED,
            self.DENIED,
            self.STALE,
            self.SUPERSEDED,
            self.CANCELLED,
        }


class PolicyVerdictType(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"
    STALE = "stale"
