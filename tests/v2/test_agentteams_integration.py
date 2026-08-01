"""Matrix Bridge 与 AgentTeams Curator Adapter 的本地合同测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from agentrig.agents.invocation_coordinator import (
    AgentInvocationCoordinator,
    AgentTaskDispatch,
)
from agentrig.agents.invocation_models import AgentRole
from agentrig.agents.invocation_schemas import AgentResultSubmit, AgentTaskEnvelope
from agentrig.agents.ports import AgentTaskContext
from agentrig.agents.schemas import CuratorInput
from agentrig.assistant import (
    AssistantMessageCreate,
    AssistantSessionCreate,
)
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome, EvaluatorType
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.repositories import SqlAssistantRepository
from agentrig.integrations.agentteams.adapters import (
    AgentTeamsEvidenceJudge,
    AgentTeamsSimulationCurator,
)
from agentrig.integrations.agentteams.bridge import AgentTeamsBridge
from agentrig.integrations.agentteams.matrix_client import MatrixClient
from agentrig.profiles.schemas import ModelConfigRef
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.runs.schemas import CaseRunDetail, RunEvent


class CompletingTransport:
    def __init__(self, services: ServiceContainer) -> None:
        self._services = services

    async def dispatch(
        self,
        invocation: object,
        envelope: AgentTaskEnvelope,
    ) -> AgentTaskDispatch:
        del invocation

        async def complete() -> None:
            await asyncio.sleep(0.01)
            await self._services.agent_invocations.claim(
                envelope.task_id,
                role=AgentRole.SIMULATION_CURATOR,
                assigned_agent="@curator:test",
            )
            current = await self._services.agent_invocations.get(envelope.task_id)
            await self._services.agent_invocations.submit_result(
                envelope.task_id,
                AgentResultSubmit(
                    idempotency_key=current.idempotency_key,
                    result={
                        "candidate": {
                            "result": {"items": [{"id": "simulated"}]},
                            "state_updates": {},
                        },
                        "model_metadata": {"model": "worker-model"},
                        "prompt_version": "simulation_curator.worker.v1",
                    },
                ),
                role=AgentRole.SIMULATION_CURATOR,
            )

        asyncio.create_task(complete())
        return AgentTaskDispatch(
            matrix_room_id="!worker:test",
            request_event_id=f"$task-{envelope.task_id}",
            assigned_agent="@curator:test",
        )


class CorrectingJudgeTransport:
    def __init__(self, services: ServiceContainer) -> None:
        self._services = services
        self.dispatches = 0

    async def dispatch(
        self,
        invocation: object,
        envelope: AgentTaskEnvelope,
    ) -> AgentTaskDispatch:
        del invocation
        self.dispatches += 1
        evidence_ref = "evt_unknown" if self.dispatches == 1 else "evt_valid"

        async def complete() -> None:
            await asyncio.sleep(0.01)
            await self._services.agent_invocations.claim(
                envelope.task_id,
                role=AgentRole.EVIDENCE_JUDGE,
                assigned_agent="@judge:test",
            )
            current = await self._services.agent_invocations.get(envelope.task_id)
            await self._services.agent_invocations.submit_result(
                envelope.task_id,
                AgentResultSubmit(
                    idempotency_key=current.idempotency_key,
                    result={
                        "verdict": "pass",
                        "summary": "supported by evidence",
                        "criteria": [],
                        "evidence_refs": [evidence_ref],
                    },
                ),
                role=AgentRole.EVIDENCE_JUDGE,
            )

        asyncio.create_task(complete())
        return AgentTaskDispatch(
            matrix_room_id="!worker:test",
            request_event_id=f"$judge-task-{self.dispatches}",
            assigned_agent="@judge:test",
        )


async def test_agentteams_curator_adapter_round_trip() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        coordinator = AgentInvocationCoordinator(
            services.agent_invocations,
            CompletingTransport(services),
            poll_interval_seconds=0.005,
        )
        adapter = AgentTeamsSimulationCurator(coordinator)
        result = await adapter.generate(
            CuratorInput(tool_name="search", arguments={"q": "hello"}),
            model_config=ModelConfigRef(
                base_url="https://model.invalid/v1",
                model="qwen3.5-plus",
                secret_ref="env:UNUSED_BY_EXTERNAL_WORKER",
            ),
            timeout_seconds=2,
            context=AgentTaskContext(
                run_id="run_adapter",
                case_run_id="case_run_adapter",
                tool_call_event_id="evt_tool_call",
            ),
        )
        assert result.candidate.result["items"][0]["id"] == "simulated"
        invocation_id = result.model_metadata["agent_invocation_id"]
        invocation = await services.agent_invocations.get(invocation_id)
        assert invocation.status.value == "completed"
        assert invocation.request_event_id == f"$task-{invocation.id}"

        corrected = await adapter.generate(
            CuratorInput(
                tool_name="search",
                arguments={"q": "hello"},
                validation_feedback=["items must be an array"],
            ),
            model_config=ModelConfigRef(
                base_url="https://model.invalid/v1",
                model="qwen3.5-plus",
                secret_ref="env:UNUSED_BY_EXTERNAL_WORKER",
            ),
            timeout_seconds=2,
            context=AgentTaskContext(
                run_id="run_adapter",
                case_run_id="case_run_adapter",
                tool_call_event_id="evt_tool_call",
            ),
        )
        correction_invocation = await services.agent_invocations.get(
            corrected.model_metadata["agent_invocation_id"]
        )
        assert correction_invocation.id != invocation.id
        assert correction_invocation.attempt == 2
    finally:
        await services.close()


async def test_agentteams_judge_retries_unknown_evidence_reference() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        transport = CorrectingJudgeTransport(services)
        adapter = AgentTeamsEvidenceJudge(
            AgentInvocationCoordinator(
                services.agent_invocations,
                transport,
                poll_interval_seconds=0.005,
            )
        )
        now = datetime.now(timezone.utc)
        draft = await adapter.evaluate(
            CaseRunDetail(
                id="case_run_judge",
                run_id="run_judge",
                case_id="case_judge",
                version="v1",
                repeat_index=1,
                comparison_pair_id=None,
                comparison_role=None,
                status=CaseRunStatus.COMPLETED,
                primary_evaluator=EvaluatorType.EVIDENCE_JUDGE,
                evaluation_state=EvaluationOutcome.AWAITING_VERDICT,
                started_at=now,
                finished_at=now,
                error_code=None,
                error_message=None,
                summary={},
                case_snapshot={"name": "judge retry", "turns": []},
                target_snapshot={},
                profile_snapshot={},
                events=[
                    RunEvent(
                        id="evt_valid",
                        case_run_id="case_run_judge",
                        seq=1,
                        event_type=RunEventType.ASSISTANT_MESSAGE,
                        payload={"content": "done"},
                        created_at=now,
                    )
                ],
            ),
            rule_result=None,
            model_config=ModelConfigRef(
                base_url="https://model.invalid/v1",
                model="qwen3.5-plus",
                secret_ref="env:UNUSED_BY_EXTERNAL_WORKER",
            ),
            timeout_seconds=2,
            context=AgentTaskContext(
                run_id="run_judge",
                case_run_id="case_run_judge",
            ),
        )
        assert draft.verdict == "pass"
        assert draft.evidence_refs == ["evt_valid"]
        assert transport.dispatches == 2
        invocation_ids = draft.model_metadata["agent_invocation_ids"]
        assert [
            (await services.agent_invocations.get(invocation_id)).attempt
            for invocation_id in invocation_ids
        ] == [1, 2]
    finally:
        await services.close()


async def test_matrix_client_and_bridge_delivery_projection() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer bridge-token"
        if request.url.path.endswith("/createRoom"):
            return httpx.Response(200, json={"room_id": "!assistant:test"})
        if "/send/m.room.message/" in request.url.path:
            return httpx.Response(200, json={"event_id": "$user-request"})
        return httpx.Response(200, json={"versions": ["v1.11"]})

    matrix = MatrixClient(
        "https://matrix.test",
        "bridge-token",
        transport=httpx.MockTransport(handle),
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    services = ServiceContainer.build(Settings(), database=database)
    await services.initialize()
    repository = SqlAssistantRepository(database)
    bridge = AgentTeamsBridge(
        enabled=True,
        assistant=services.assistant,
        repository=repository,
        client=matrix,
        bridge_user_id="@bridge:test",
        manager_user_id="@manager:test",
        curator_user_id="@curator:test",
        judge_user_id="@judge:test",
    )
    try:
        session = await services.assistant.create_session(
            AssistantSessionCreate(title="Matrix contract"),
            created_by="user",
        )
        session = await bridge.ensure_room(session)
        assert session.matrix_room_id == "!assistant:test"
        receipt = await services.assistant.send_message(
            session.id,
            AssistantMessageCreate(
                client_message_id="matrix-message-1",
                content="evaluate this",
            ),
            actor_id="user",
        )
        await bridge.dispatch_user_message(receipt.event_id, receipt.turn_id)
        delivered = await services.assistant.get_event(receipt.event_id)
        turn = await services.assistant.get_turn(receipt.turn_id)
        assert delivered.delivery_status.value == "delivered"
        assert turn.status.value == "dispatched"

        await bridge._project_response(  # noqa: SLF001 - Matrix contract boundary
            {
                "next_batch": "sync-2",
                "rooms": {
                    "join": {
                        "!assistant:test": {
                            "timeline": {
                                "events": [
                                    {
                                        "type": "m.room.message",
                                        "event_id": "$manager-response",
                                        "sender": "@manager:test",
                                        "origin_server_ts": int(
                                            datetime.now(timezone.utc).timestamp() * 1000
                                        ),
                                        "content": {
                                            "msgtype": "m.text",
                                            "body": "I prepared a plan.",
                                            "org.agentrig.turn_id": receipt.turn_id,
                                        },
                                    }
                                ]
                            }
                        }
                    }
                },
            }
        )
        projected = await services.assistant.list_events(session.id)
        assert projected.items[-1].event_type.value == "assistant_message"
        assert projected.items[-1].matrix_event_id == "$manager-response"
        assert (await services.assistant.get_turn(receipt.turn_id)).status.value == "completed"
        assert any("createRoom" in request.url.path for request in requests)
    finally:
        await services.close()
