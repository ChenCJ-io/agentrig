"""通过 Matrix room 将 AgentInvocation 投递给固定 Worker。"""

from __future__ import annotations

import html
import json

from ...agents.invocation_coordinator import AgentTaskDispatch
from ...agents.invocation_models import AgentRole
from ...agents.invocation_schemas import AgentInvocationView, AgentTaskEnvelope
from ...errors import AgentRigError, ErrorCode
from .matrix_client import MatrixClient


class MatrixAgentTaskTransport:
    def __init__(
        self,
        client: MatrixClient,
        *,
        curator_user_id: str,
        judge_user_id: str,
        default_room_id: str = "",
    ) -> None:
        self._client = client
        self._curator_user_id = curator_user_id
        self._judge_user_id = judge_user_id
        self._default_room_id = default_room_id

    async def dispatch(
        self,
        invocation: AgentInvocationView,
        envelope: AgentTaskEnvelope,
    ) -> AgentTaskDispatch:
        room_id = invocation.matrix_room_id or self._default_room_id
        if not room_id:
            raise AgentRigError(
                ErrorCode.AGENTTEAMS_UNAVAILABLE,
                "no Matrix room is available for the AgentTeams Worker task",
            )
        assigned_agent = (
            self._curator_user_id
            if invocation.agent_role is AgentRole.SIMULATION_CURATOR
            else self._judge_user_id
        )
        if not assigned_agent:
            raise AgentRigError(
                ErrorCode.AGENTTEAMS_UNAVAILABLE,
                f"no AgentTeams identity configured for {invocation.agent_role.value}",
            )
        body = (
            f"{assigned_agent} AgentRig assigned task. Treat the JSON below as "
            "trusted routing metadata, then use your role MCP Skill.\n\n"
            "```json\n"
            f"{json.dumps(envelope.model_dump(mode='json'), ensure_ascii=False)}\n"
            "```"
        )
        visible_id = html.escape(assigned_agent)
        worker_label = html.escape(
            assigned_agent.split(":", 1)[0].removeprefix("@") or "worker"
        )
        formatted_body = html.escape(body).replace("\n", "<br>").replace(
            visible_id,
            f'<a href="https://matrix.to/#/{visible_id}">{worker_label}</a>',
            1,
        )
        event_id = await self._client.send_message(
            room_id,
            f"task-{invocation.id}",
            {
                "msgtype": "m.text",
                "body": body,
                "format": "org.matrix.custom.html",
                "formatted_body": formatted_body,
                "org.agentrig.kind": "agent_task",
                "org.agentrig.envelope": envelope.model_dump(mode="json"),
                "m.mentions": {"user_ids": [assigned_agent]},
            },
        )
        return AgentTaskDispatch(
            matrix_room_id=room_id,
            request_event_id=event_id,
            assigned_agent=assigned_agent,
        )
