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


class RunEventType(StrEnum):
    USER_MESSAGE = "user_message"
    DRIVER_REQUEST = "driver_request"
    DRIVER_SESSION = "driver_session"
    ASSISTANT_TEXT = "assistant_text"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    PROVIDER_ATTEMPT = "provider_attempt"
    TOOL_RESULT = "tool_result"
    VALIDATION = "validation"
    USAGE = "usage"
    ERROR = "error"
