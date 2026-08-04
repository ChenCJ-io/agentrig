"""V2 助手、计划和协作投影的有限状态集合。"""

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
    DECISION_RECORDED = "decision_recorded"
    DECISION_STATUS_CHANGED = "decision_status_changed"
    RECOVERY_PROPOSED = "recovery_proposed"
    RUN_STATUS = "run_status"
    AGENT_INVOCATION_STATUS = "agent_invocation_status"
    COLLABORATION_INTERVENTION = "collaboration_intervention"
    SYSTEM_NOTICE = "system_notice"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    MANAGER = "manager"
    WORKER = "worker"
    SYSTEM = "system"


class DeliveryStatus(StrEnum):
    LOCAL = "local"
    PENDING = "pending"
    DELIVERED = "delivered"
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
