"""AgentRig V2 Assistant 与 EvaluationPlan HTTP/SSE API。"""

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

from .api_params import EventLimit, EventSequence, PageLimit, PageOffset
from .assistant.models import ActorType
from .assistant.schemas import (
    AssistantMessageCreate,
    AssistantProviderHealth,
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
    header = services(request).settings.server.trusted_principal_header
    if header is None:
        return "web-user"
    value = request.headers.get(header, "").strip()
    return value[:300] if value else "web-user"


@router.post(
    "/assistant/sessions",
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: Request,
    value: AssistantSessionCreate,
) -> object:
    container = services(request)
    return await container.assistant.create_session(
        value,
        created_by=principal(request),
    )


@router.get("/assistant/sessions")
async def list_sessions(
    request: Request,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).assistant.list_sessions(limit=limit, offset=offset)


@router.get("/assistant/sessions/{session_id}")
async def get_session(request: Request, session_id: str) -> object:
    return await services(request).assistant.get_session(session_id)


@router.get("/assistant/turns/{turn_id}")
async def get_turn(request: Request, turn_id: str) -> object:
    return await services(request).assistant.get_turn(turn_id)


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
    if not container.basic_assistant.health().available:
        raise AgentRigError(
            code=ErrorCode.ASSISTANT_PROVIDER_UNAVAILABLE,
            message="智能评测助手未配置可用的模型 Provider",
            retryable=True,
        )
    receipt = await container.assistant.send_message(
        session_id,
        value,
        actor_id=principal(request),
    )
    background.add_task(
        container.basic_assistant.process,
        receipt.event_id,
        receipt.turn_id,
    )
    return receipt


@router.get("/assistant/provider-health")
async def assistant_provider_health(request: Request) -> object:
    container = services(request)
    basic = container.basic_assistant.health()
    if basic.available:
        return basic
    return AssistantProviderHealth(
        enabled=False,
        available=False,
        provider="none",
        message=basic.message,
    )


@router.get("/assistant/sessions/{session_id}/events")
async def list_events(
    request: Request,
    session_id: str,
    after_seq: EventSequence = 0,
    limit: EventLimit = 100,
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
    after_seq: EventSequence = 0,
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


@router.post("/target-chats", status_code=status.HTTP_201_CREATED)
async def create_target_chat(request: Request, value: TargetChatCreate) -> object:
    return await services(request).target_chats.create(value)


@router.get("/target-chats")
async def list_target_chats(
    request: Request,
    target_id: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
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
