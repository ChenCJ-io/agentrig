"""跨入口共享的结构化业务错误。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TARGET_UNREACHABLE = "target_unreachable"
    DRIVER_CAPABILITY_MISSING = "driver_capability_missing"
    VERSION_INCOMPATIBLE = "version_incompatible"
    INVALID_EVALUATION_CONFIG = "invalid_evaluation_config"
    PROVIDER_EXHAUSTED = "provider_exhausted"
    TOOL_RESULT_INVALID = "tool_result_invalid"
    CASE_TIMEOUT = "case_timeout"
    COMPONENT_TIMEOUT = "component_timeout"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    EVALUATION_ERROR = "evaluation_error"
    CONFLICT = "conflict"
    INTERNAL_ERROR = "internal_error"


class ErrorDetail(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class AgentRigError(Exception):
    """Service 层抛出的、可安全投影到 HTTP/MCP 的错误。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(
            code=code,
            message=message,
            details=details or {},
            retryable=retryable,
        )
