"""V2 助手与计划的有限状态集合。"""

from enum import StrEnum


class AssistantSessionStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class AssistantEventType(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    ASSISTANT_ACTIVITY = "assistant_activity"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_CONFIRMED = "plan_confirmed"
    PLAN_SUBMITTED = "plan_submitted"
    RUN_STATUS = "run_status"
    SYSTEM_NOTICE = "system_notice"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    MANAGER = "manager"
    SYSTEM = "system"


class DeliveryStatus(StrEnum):
    LOCAL = "local"
    FAILED = "failed"


class AssistantTurnStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationPlanStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
