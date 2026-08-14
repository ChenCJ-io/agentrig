"""运行和证据的稳定状态枚举。"""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class CaseRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class FailureClass(StrEnum):
    BEHAVIOR_REGRESSION = "behavior_regression"
    TARGET_UNREACHABLE = "target_unreachable"
    TOOL_RESULT_UNAVAILABLE = "tool_result_unavailable"
    CONTRACT_INCOMPATIBLE = "contract_incompatible"
    TIMEOUT = "timeout"
    EVALUATION_ERROR = "evaluation_error"
    POLICY_DENIED = "policy_denied"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    INTERNAL_ERROR = "internal_error"
    UNKNOWN = "unknown"


class RunEventType(StrEnum):
    USER_MESSAGE = "user_message"
    DRIVER_REQUEST = "driver_request"
    DRIVER_SESSION = "driver_session"
    CAPABILITY_SNAPSHOT = "capability_snapshot"
    SESSION_STATUS = "session_status"
    MODEL_CALL = "model_call"
    THINKING = "thinking"
    DATA_PART = "data_part"
    ASSISTANT_TEXT = "assistant_text"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    PROVIDER_ATTEMPT = "provider_attempt"
    TOOL_RESULT = "tool_result"
    TOOL_LIFECYCLE = "tool_lifecycle"
    PERMISSION = "permission"
    EXTERNAL_EXECUTION = "external_execution"
    LIFECYCLE = "lifecycle"
    AGENT_LIFECYCLE = "agent_lifecycle"
    MEMORY_OPERATION = "memory_operation"
    WORKSPACE_ARTIFACT = "workspace_artifact"
    VALIDATION = "validation"
    USAGE = "usage"
    ERROR = "error"
