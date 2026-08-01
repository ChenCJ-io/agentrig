"""AgentRig AssistantEvent 与 AgentTeams Matrix room 的可靠投影桥。"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from contextlib import suppress
from typing import Any

import httpx
from pydantic import BaseModel

from ...assistant.models import (
    ActorType,
    AssistantEventType,
    AssistantTurnStatus,
    DeliveryStatus,
)
from ...assistant.repository import AssistantRepository
from ...assistant.schemas import AssistantSessionView
from ...assistant.service import AssistantService
from ...errors import AgentRigError, ErrorCode
from .matrix_client import MatrixClient

logger = logging.getLogger("agentrig.agentteams")
_TURN_MARKER = re.compile(r"^\s*\[agentrig-turn:([^\]]+)\]\s*", re.IGNORECASE)


class AgentTeamsHealth(BaseModel):
    enabled: bool
    configured: bool
    matrix_reachable: bool
    runtime_reachable: bool | None = None
    message: str


class AgentTeamsBridge:
    _CURSOR = "agentteams_matrix"

    def __init__(
        self,
        *,
        enabled: bool,
        assistant: AssistantService,
        repository: AssistantRepository,
        client: MatrixClient | None,
        bridge_user_id: str,
        manager_user_id: str,
        curator_user_id: str,
        judge_user_id: str,
        runtime_health_url: str = "",
        role_mcp_configured: bool = True,
    ) -> None:
        self._enabled = enabled
        self._assistant = assistant
        self._repository = repository
        self._client = client
        self._bridge_user_id = bridge_user_id
        self._manager_user_id = manager_user_id
        self._curator_user_id = curator_user_id
        self._judge_user_id = judge_user_id
        self._runtime_health_url = runtime_health_url
        self._role_mcp_configured = role_mcp_configured
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self._room_locks: dict[str, asyncio.Lock] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def start(self) -> None:
        if not self._enabled or self._client is None or self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._sync_loop(), name="agentteams-matrix-sync")

    async def close(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def health(self) -> AgentTeamsHealth:
        configured = self._client is not None and self._role_mcp_configured and all(
            (
                self._bridge_user_id,
                self._manager_user_id,
                self._curator_user_id,
                self._judge_user_id,
            )
        )
        if not self._enabled:
            return AgentTeamsHealth(
                enabled=False,
                configured=configured,
                matrix_reachable=False,
                message="AgentTeams integration is disabled; V1 local agents remain active",
            )
        if self._client is None:
            return AgentTeamsHealth(
                enabled=True,
                configured=False,
                matrix_reachable=False,
                message="Matrix homeserver or bridge token is not configured",
            )
        matrix_reachable = False
        runtime_reachable: bool | None = None
        messages: list[str] = []
        if not configured:
            messages.append("Matrix identities or role MCP tokens are incomplete")
        try:
            await self._client.versions()
            matrix_reachable = True
        except Exception as exc:
            messages.append(f"Matrix unavailable: {exc}")
        if self._runtime_health_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(self._runtime_health_url)
                    response.raise_for_status()
                runtime_reachable = True
            except Exception as exc:
                runtime_reachable = False
                messages.append(f"AgentTeams runtime unavailable: {exc}")
        healthy = configured and matrix_reachable and runtime_reachable is not False
        return AgentTeamsHealth(
            enabled=True,
            configured=configured,
            matrix_reachable=matrix_reachable,
            runtime_reachable=runtime_reachable,
            message="AgentTeams integration is healthy" if healthy else "; ".join(messages),
        )

    async def ensure_room(self, session: AssistantSessionView) -> AssistantSessionView:
        if session.matrix_room_id:
            return session
        lock = self._room_locks.setdefault(session.id, asyncio.Lock())
        async with lock:
            current = await self._assistant.get_session(session.id)
            if current.matrix_room_id:
                return current
            client = self._require_client()
            room_id = await client.create_room(
                name=f"AgentRig · {current.title}",
                topic=f"AgentRig assistant session {current.id}",
                invite=[
                    self._manager_user_id,
                    self._curator_user_id,
                    self._judge_user_id,
                ],
            )
            return await self._assistant.set_matrix_room(current.id, room_id)

    async def dispatch_user_message(self, event_id: str, turn_id: str) -> None:
        event = await self._assistant.get_event(event_id)
        turn = await self._assistant.get_turn(turn_id)
        if event.turn_id != turn.id or event.session_id != turn.session_id:
            raise AgentRigError(
                ErrorCode.ASSISTANT_TURN_CONFLICT,
                "message event and assistant turn do not match",
            )
        session = await self.ensure_room(await self._assistant.get_session(event.session_id))
        assert session.matrix_room_id is not None
        client = self._require_client()
        try:
            active_plan_id = event.payload.get("active_plan_id")
            envelope = (
                f"{self._manager_user_id} AgentRig Manager request.\n\n"
                "[AgentRig request envelope — trusted routing metadata]\n"
                f"assistant_session_id: {event.session_id}\n"
                f"assistant_turn_id: {turn.id}\n"
                f"user_event_id: {event.id}\n"
                f"active_plan_id: {active_plan_id or 'none'}\n"
                "[/AgentRig request envelope]\n\n"
                "Use the AgentRig Manager MCP and the matching Skill. "
                f"Begin the final room reply with [agentrig-turn:{turn.id}] so the "
                "Web turn can be correlated.\n\n"
                f"User request:\n{event.payload['content']}"
            )
            formatted_envelope = html.escape(envelope).replace("\n", "<br>")
            manager_label = html.escape(
                self._manager_user_id.split(":", 1)[0].removeprefix("@")
                or "manager"
            )
            visible_id = html.escape(self._manager_user_id)
            formatted_envelope = formatted_envelope.replace(
                visible_id,
                f'<a href="https://matrix.to/#/{visible_id}">{manager_label}</a>',
                1,
            )
            matrix_event_id = await client.send_message(
                session.matrix_room_id,
                f"assistant-turn-{turn.id}",
                {
                    "msgtype": "m.text",
                    "body": envelope,
                    "format": "org.matrix.custom.html",
                    "formatted_body": formatted_envelope,
                    "org.agentrig.kind": event.event_type.value,
                    "org.agentrig.session_id": event.session_id,
                    "org.agentrig.turn_id": turn.id,
                    "org.agentrig.event_id": event.id,
                    "org.agentrig.active_plan_id": event.payload.get("active_plan_id"),
                    "m.mentions": {"user_ids": [self._manager_user_id]},
                },
            )
        except Exception as exc:
            await self._repository.mark_event_delivery(
                event.id,
                DeliveryStatus.FAILED,
                last_error=str(exc),
            )
            raise AgentRigError(
                ErrorCode.MATRIX_DELIVERY_FAILED,
                f"failed to deliver assistant message: {exc}",
                retryable=True,
            ) from exc
        await self._repository.mark_event_delivery(
            event.id,
            DeliveryStatus.DELIVERED,
            matrix_event_id=matrix_event_id,
        )
        await self._repository.set_turn_status(
            turn.id,
            AssistantTurnStatus.DISPATCHED,
            matrix_request_event_id=matrix_event_id,
        )

    async def retry_event(self, event_id: str) -> None:
        event = await self._assistant.get_event(event_id)
        if event.turn_id is None or event.event_type is not AssistantEventType.USER_MESSAGE:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "only a user message delivery can be retried",
            )
        await self.dispatch_user_message(event.id, event.turn_id)

    async def collaboration(self, session_id: str) -> dict[str, Any]:
        session = await self._assistant.get_session(session_id)
        return {
            "session_id": session.id,
            "matrix_room_id": session.matrix_room_id,
            "manager_user_id": self._manager_user_id,
            "curator_user_id": self._curator_user_id,
            "judge_user_id": self._judge_user_id,
        }

    async def _sync_loop(self) -> None:
        cursor = await self._repository.get_integration_cursor(self._CURSOR)
        while not self._stopping.is_set():
            try:
                response = await self._require_client().sync(since=cursor)
                await self._project_response(response)
                next_batch = response.get("next_batch")
                if isinstance(next_batch, str):
                    cursor = next_batch
                    await self._repository.save_integration_cursor(
                        self._CURSOR,
                        cursor,
                        {"source": "matrix_sync"},
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AgentTeams Matrix sync failed")
                await asyncio.sleep(2.0)

    async def _project_response(self, response: dict[str, Any]) -> None:
        rooms = response.get("rooms")
        joined = rooms.get("join") if isinstance(rooms, dict) else None
        if not isinstance(joined, dict):
            return
        for room_id, room_data in joined.items():
            timeline = room_data.get("timeline") if isinstance(room_data, dict) else None
            events = timeline.get("events") if isinstance(timeline, dict) else None
            if not isinstance(events, list):
                continue
            for raw in events:
                if isinstance(raw, dict):
                    await self._project_event(str(room_id), raw)

    async def _project_event(self, room_id: str, raw: dict[str, Any]) -> None:
        if raw.get("type") != "m.room.message":
            return
        sender = raw.get("sender")
        matrix_event_id = raw.get("event_id")
        content = raw.get("content")
        if (
            not isinstance(sender, str)
            or sender == self._bridge_user_id
            or not isinstance(matrix_event_id, str)
            or not isinstance(content, dict)
        ):
            return
        if await self._repository.get_event_by_matrix_id(matrix_event_id) is not None:
            return
        session = await self._repository.get_session_by_matrix_room(room_id)
        if session is None:
            return
        turn_id_value = content.get("org.agentrig.turn_id")
        turn_id = turn_id_value if isinstance(turn_id_value, str) else None
        body = content.get("body")
        projected_body = body if isinstance(body, str) else ""
        if sender == self._manager_user_id:
            marker = _TURN_MARKER.match(projected_body)
            if marker is not None:
                turn_id = marker.group(1)
                projected_body = projected_body[marker.end() :]
            referenced_turn = (
                await self._repository.get_turn(turn_id)
                if turn_id is not None
                else None
            )
            if referenced_turn is None or referenced_turn.session_id != session.id:
                open_turn = await self._repository.get_latest_open_turn(session.id)
                turn_id = open_turn.id if open_turn is not None else None
        elif turn_id is not None:
            referenced_turn = await self._repository.get_turn(turn_id)
            if referenced_turn is None or referenced_turn.session_id != session.id:
                turn_id = None
        payload = {
            "content": projected_body,
            "source": "agentteams_matrix",
        }
        if sender == self._manager_user_id:
            event_type = AssistantEventType.ASSISTANT_MESSAGE
            actor_type = ActorType.MANAGER
        elif sender in {self._curator_user_id, self._judge_user_id}:
            event_type = AssistantEventType.ASSISTANT_ACTIVITY
            actor_type = ActorType.WORKER
        else:
            event_type = AssistantEventType.COLLABORATION_INTERVENTION
            actor_type = ActorType.USER
        await self._assistant.append_event(
            session.id,
            event_type,
            actor_type=actor_type,
            actor_id=sender,
            payload=payload,
            turn_id=turn_id,
            matrix_event_id=matrix_event_id,
            delivery_status=DeliveryStatus.DELIVERED,
        )
        if turn_id is not None:
            status = (
                AssistantTurnStatus.COMPLETED
                if event_type is AssistantEventType.ASSISTANT_MESSAGE
                else AssistantTurnStatus.RUNNING
            )
            await self._repository.set_turn_status(
                turn_id,
                status,
                **(
                    {"matrix_response_event_id": matrix_event_id}
                    if status is AssistantTurnStatus.COMPLETED
                    else {}
                ),
            )

    def _require_client(self) -> MatrixClient:
        if not self._enabled or self._client is None:
            raise AgentRigError(
                ErrorCode.AGENTTEAMS_UNAVAILABLE,
                "AgentTeams Matrix bridge is disabled or not configured",
                retryable=True,
            )
        return self._client
