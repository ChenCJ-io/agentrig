"""AgentRig V2 Assistant、EvaluationPlan 与 AgentTeams HTTP/SSE API。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from .assistant.models import ActorType
from .assistant.schemas import (
    AssistantMessageCreate,
    AssistantSessionCreate,
    EvaluationPlanConfirm,
    EvaluationPlanCreate,
    EvaluationPlanPatch,
    EvaluationPlanSubmit,
)
from .bootstrap import ServiceContainer
from .errors import AgentRigError, ErrorCode
from .target_chat import (
    TargetChatCreate,
    TargetChatDraftCaseCreate,
    TargetChatDraftSampleCreate,
    TargetChatMessage,
)

logger = logging.getLogger("agentrig.v2_api")
router = APIRouter(prefix="/api/v2", tags=["AgentRig V2"])


def services(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.services)


def principal(request: Request) -> str:
    return request.headers.get("x-agentrig-principal", "web-user")[:300]


@router.post(
    "/assistant/sessions",
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: Request,
    value: AssistantSessionCreate,
    background: BackgroundTasks,
) -> object:
    container = services(request)
    session = await container.assistant.create_session(
        value,
        created_by=principal(request),
    )
    if container.agentteams_bridge.enabled:
        background.add_task(_ensure_room, container, session.id)
    return session


@router.get("/assistant/sessions")
async def list_sessions(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).assistant.list_sessions(limit=limit, offset=offset)


@router.get("/assistant/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> object:
    return await services(request).assistant.get_session(session_id)


@router.post("/assistant/sessions/{session_id}/archive")
async def archive_session(request: Request, session_id: str) -> object:
    return await services(request).assistant.archive_session(session_id)


@router.post(
    "/assistant/sessions/{session_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_message(
    request: Request,
    session_id: str,
    value: AssistantMessageCreate,
    background: BackgroundTasks,
) -> object:
    container = services(request)
    if len(value.content) > container.settings.assistant.max_message_chars:
        raise AgentRigError(
            code=ErrorCode.VALIDATION_ERROR,
            message="assistant message exceeds the configured length limit",
        )
    if not container.agentteams_bridge.enabled:
        raise AgentRigError(
            code=ErrorCode.AGENTTEAMS_UNAVAILABLE,
            message="V2 assistant messaging requires AgentTeams to be enabled",
            retryable=True,
        )
    receipt = await container.assistant.send_message(
        session_id,
        value,
        actor_id=principal(request),
    )
    background.add_task(
        _deliver_message,
        container,
        receipt.event_id,
        receipt.turn_id,
    )
    return receipt


@router.get("/assistant/sessions/{session_id}/events")
async def list_events(
    request: Request,
    session_id: str,
    after_seq: int = 0,
    limit: int = 100,
) -> object:
    return await services(request).assistant.list_events(
        session_id,
        after_seq=after_seq,
        limit=limit,
    )


@router.get("/assistant/sessions/{session_id}/stream")
async def stream_events(
    request: Request,
    session_id: str,
    after_seq: int = 0,
) -> StreamingResponse:
    container = services(request)
    await container.assistant.get_session(session_id)

    async def events() -> AsyncIterator[str]:
        cursor = max(0, after_seq)
        last_heartbeat = time.monotonic()
        while not await request.is_disconnected():
            page = await container.assistant.list_events(
                session_id,
                after_seq=cursor,
                limit=200,
            )
            for item in page.items:
                cursor = item.seq
                data = json.dumps(
                    jsonable_encoder(item),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: assistant_event\nid: {item.seq}\ndata: {data}\n\n"
            now = time.monotonic()
            if now - last_heartbeat >= container.settings.assistant.sse_heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_heartbeat = now
            await asyncio.sleep(container.settings.assistant.sse_poll_interval_seconds)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/assistant/turns/{turn_id}/cancel")
async def cancel_turn(request: Request, turn_id: str) -> object:
    return await services(request).assistant.cancel_turn(turn_id)


@router.post("/assistant/events/{event_id}/retry-delivery")
async def retry_delivery(request: Request, event_id: str) -> object:
    container = services(request)
    await container.agentteams_bridge.retry_event(event_id)
    return await container.assistant.get_event(event_id)


@router.post("/evaluation-plans", status_code=status.HTTP_201_CREATED)
async def create_evaluation_plan(
    request: Request,
    value: EvaluationPlanCreate,
) -> object:
    return await services(request).evaluation_plans.create(
        value.model_copy(update={"created_by": principal(request)})
    )


@router.get("/evaluation-plans/{plan_id}")
async def get_evaluation_plan(request: Request, plan_id: str) -> object:
    return await services(request).evaluation_plans.get(plan_id)


@router.patch("/evaluation-plans/{plan_id}")
async def update_evaluation_plan(
    request: Request,
    plan_id: str,
    value: EvaluationPlanPatch,
) -> object:
    return await services(request).evaluation_plans.update(
        plan_id,
        value,
        actor_type=ActorType.USER,
        actor_id=principal(request),
    )


@router.post("/evaluation-plans/{plan_id}/validate")
async def validate_evaluation_plan(request: Request, plan_id: str) -> object:
    return await services(request).evaluation_plans.validate(plan_id)


@router.post("/evaluation-plans/{plan_id}/confirm")
async def confirm_evaluation_plan(
    request: Request,
    plan_id: str,
    value: EvaluationPlanConfirm,
) -> object:
    return await services(request).evaluation_plans.confirm(
        plan_id,
        value.model_copy(update={"confirmed_by": principal(request)}),
    )


@router.post("/evaluation-plans/{plan_id}/cancel")
async def cancel_evaluation_plan(request: Request, plan_id: str) -> object:
    return await services(request).evaluation_plans.cancel(plan_id)


@router.post("/evaluation-plans/{plan_id}/submit")
async def submit_evaluation_plan(
    request: Request,
    plan_id: str,
    value: EvaluationPlanSubmit,
) -> object:
    plan, run = await services(request).evaluation_plans.submit(plan_id, value)
    return {"plan": plan, "run": run}


@router.get("/agent-invocations/{invocation_id}")
async def get_agent_invocation(request: Request, invocation_id: str) -> object:
    return await services(request).agent_invocations.get(invocation_id)


@router.get("/agent-invocations")
async def list_all_agent_invocations(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).agent_invocations.list_all(
        limit=limit,
        offset=offset,
    )


@router.get("/assistant/sessions/{session_id}/agent-invocations")
async def list_agent_invocations(
    request: Request,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
) -> object:
    await services(request).assistant.get_session(session_id)
    return await services(request).agent_invocations.list_for_session(
        session_id,
        limit=limit,
        offset=offset,
    )


@router.get("/agentteams/health")
async def agentteams_health(request: Request) -> object:
    return await services(request).agentteams_bridge.health()


@router.get("/agentteams/collaboration/{session_id}")
async def agentteams_collaboration(request: Request, session_id: str) -> object:
    return await services(request).agentteams_bridge.collaboration(session_id)


@router.post("/target-chats", status_code=status.HTTP_201_CREATED)
async def create_target_chat(request: Request, value: TargetChatCreate) -> object:
    return await services(request).target_chats.create(value)


@router.get("/target-chats")
async def list_target_chats(
    request: Request,
    target_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).target_chats.list_sessions(
        target_id=target_id,
        limit=limit,
        offset=offset,
    )


@router.get("/target-chats/{chat_id}")
async def get_target_chat(request: Request, chat_id: str) -> object:
    return await services(request).target_chats.get(chat_id)


@router.post("/target-chats/{chat_id}/messages")
async def send_target_chat_message(
    request: Request,
    chat_id: str,
    value: TargetChatMessage,
) -> object:
    return await services(request).target_chats.send(chat_id, value)


@router.post("/target-chats/{chat_id}/close")
async def close_target_chat(request: Request, chat_id: str) -> object:
    return await services(request).target_chats.close(chat_id)


@router.post(
    "/target-chats/{chat_id}/draft-case",
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_case_from_target_chat(
    request: Request,
    chat_id: str,
    value: TargetChatDraftCaseCreate,
) -> object:
    return await services(request).target_chats.create_draft_case(chat_id, value)


@router.post(
    "/target-chats/{chat_id}/draft-sample",
    status_code=status.HTTP_201_CREATED,
)
async def create_draft_sample_from_target_chat(
    request: Request,
    chat_id: str,
    value: TargetChatDraftSampleCreate,
) -> object:
    return await services(request).target_chats.create_draft_sample(chat_id, value)


async def _ensure_room(container: ServiceContainer, session_id: str) -> None:
    try:
        session = await container.assistant.get_session(session_id)
        await container.agentteams_bridge.ensure_room(session)
    except Exception:
        logger.exception("failed to create Matrix room for %s", session_id)


async def _deliver_message(
    container: ServiceContainer,
    event_id: str,
    turn_id: str,
) -> None:
    try:
        await container.agentteams_bridge.dispatch_user_message(event_id, turn_id)
    except Exception:
        logger.exception("failed to deliver assistant event %s", event_id)
