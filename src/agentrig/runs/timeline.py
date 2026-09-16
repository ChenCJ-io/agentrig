"""将 RunEvent 与 EvaluationResult 投影为统一、稳定的证据时间线。"""

from __future__ import annotations

from typing import Any

from .models import RunEventType
from .schemas import CaseRunDetail, EvidenceTimelineItem

_EVENT_PRESENTATION: dict[RunEventType, tuple[str, str]] = {
    RunEventType.USER_MESSAGE: ("用户", "发送测试消息"),
    RunEventType.DRIVER_REQUEST: ("被测 Agent", "处理请求"),
    RunEventType.DRIVER_SESSION: ("被测 Agent", "会话状态变化"),
    RunEventType.CAPABILITY_SNAPSHOT: ("AgentRig", "冻结能力快照"),
    RunEventType.SESSION_STATUS: ("被测 Agent", "会话状态变化"),
    RunEventType.MODEL_CALL: ("被测 Agent", "调用模型"),
    RunEventType.THINKING: ("被测 Agent", "生成推理事件"),
    RunEventType.DATA_PART: ("被测 Agent", "返回结构化数据"),
    RunEventType.ASSISTANT_TEXT: ("被测 Agent", "返回文本"),
    RunEventType.ASSISTANT_MESSAGE: ("被测 Agent", "返回消息"),
    RunEventType.TOOL_CALL: ("被测 Agent", "调用工具"),
    RunEventType.PROVIDER_ATTEMPT: ("结果提供器", "获取工具结果"),
    RunEventType.TOOL_RESULT: ("结果提供器", "返回工具结果"),
    RunEventType.TOOL_LIFECYCLE: ("被测 Agent", "工具调用状态变化"),
    RunEventType.PERMISSION: ("安全策略", "执行权限判定"),
    RunEventType.EXTERNAL_EXECUTION: ("外部执行器", "执行外部任务"),
    RunEventType.LIFECYCLE: ("AgentRig", "运行状态变化"),
    RunEventType.AGENT_LIFECYCLE: ("被测 Agent", "Agent 状态变化"),
    RunEventType.MEMORY_OPERATION: ("被测 Agent", "执行记忆操作"),
    RunEventType.WORKSPACE_ARTIFACT: ("被测 Agent", "生成工作区产物"),
    RunEventType.VALIDATION: ("AgentRig", "执行契约校验"),
    RunEventType.USAGE: ("AgentRig", "记录资源用量"),
    RunEventType.ERROR: ("AgentRig", "记录执行错误"),
}


def build_evidence_timeline(
    cell_id: str,
    attempts: list[CaseRunDetail],
) -> list[EvidenceTimelineItem]:
    items: list[EvidenceTimelineItem] = []
    for attempt in sorted(attempts, key=lambda item: (item.attempt_index, item.id)):
        attempt_id = attempt.attempt_id or attempt.id
        for event in sorted(
            attempt.events,
            key=lambda item: (item.created_at, item.seq, item.id),
        ):
            actor, title = _EVENT_PRESENTATION[event.event_type]
            items.append(
                EvidenceTimelineItem(
                    id=f"timeline:event:{event.id}",
                    cell_id=cell_id,
                    attempt_id=attempt_id,
                    case_run_id=attempt.id,
                    attempt_index=attempt.attempt_index,
                    source_type="event",
                    source_id=event.id,
                    category=event.event_type.value,
                    actor=actor,
                    status=_event_status(event.payload),
                    title=title,
                    summary=_event_summary(event.payload),
                    evidence_refs=[event.id],
                    payload=event.payload,
                    occurred_at=event.created_at,
                )
            )
        for evaluation in sorted(
            attempt.evaluations,
            key=lambda item: (item.created_at, item.id),
        ):
            items.append(
                EvidenceTimelineItem(
                    id=f"timeline:evaluation:{evaluation.id}",
                    cell_id=cell_id,
                    attempt_id=attempt_id,
                    case_run_id=attempt.id,
                    attempt_index=attempt.attempt_index,
                    source_type="evaluation",
                    source_id=evaluation.id,
                    category=f"evaluation.{evaluation.evaluator_type.value}",
                    actor="评判器",
                    status=evaluation.verdict or evaluation.status.value,
                    title=f"{evaluation.evaluator_type.value} 评判完成",
                    summary=evaluation.summary,
                    evidence_refs=evaluation.evidence_refs,
                    payload={
                        "evaluator_source": evaluation.evaluator_source,
                        "criteria": [
                            item.model_dump(mode="json")
                            for item in evaluation.criteria
                        ],
                    },
                    occurred_at=evaluation.updated_at,
                )
            )
    return sorted(
        items,
        key=lambda item: (
            item.occurred_at,
            item.attempt_index,
            0 if item.source_type == "event" else 1,
            item.source_id,
        ),
    )


def _event_status(payload: dict[str, Any]) -> str | None:
    for key in ("status", "outcome", "verdict", "phase"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _event_summary(payload: dict[str, Any]) -> str | None:
    for key in ("summary", "message", "text", "error_message", "reason"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
