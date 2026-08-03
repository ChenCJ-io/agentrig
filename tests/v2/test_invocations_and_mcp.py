"""AgentInvocation 角色隔离与三类 MCP 工具面。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from agentrig.agents.invocation_models import AgentInvocationStatus, AgentRole
from agentrig.agents.invocation_schemas import AgentInvocationCreate, AgentResultSubmit
from agentrig.agents.ports import AgentTaskContext
from agentrig.assistant import AssistantMessageCreate, AssistantSessionCreate
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.infrastructure.database import Database
from agentrig.mcp_server import create_role_mcp_servers


@pytest.fixture
async def services() -> ServiceContainer:
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await container.initialize()
    yield container
    await container.close()


async def test_invocation_role_state_and_result_idempotency(
    services: ServiceContainer,
) -> None:
    invocation = await services.agent_invocations.create_or_get(
        AgentInvocationCreate(
            role=AgentRole.SIMULATION_CURATOR,
            context=AgentTaskContext(run_id="run_v2", case_run_id="case_run_v2"),
            input_snapshot={
                "kind": "simulation_curator",
                "input": {"api_key": "must-not-persist"},
            },
            deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
            idempotency_key="curator-task-1",
            matrix_room_id="!room:test",
        )
    )
    assert invocation.input_snapshot["input"]["api_key"] == "[REDACTED]"
    await services.agent_invocations.mark_dispatched(
        invocation.id,
        matrix_room_id="!room:test",
        request_event_id="$request",
        assigned_agent="curator",
    )
    with pytest.raises(AgentRigError) as forbidden:
        await services.agent_invocations.claim(
            invocation.id,
            role=AgentRole.EVIDENCE_JUDGE,
            assigned_agent="judge",
        )
    assert forbidden.value.detail.code is ErrorCode.AGENT_ROLE_FORBIDDEN
    claimed = await services.agent_invocations.claim(
        invocation.id,
        role=AgentRole.SIMULATION_CURATOR,
        assigned_agent="curator",
    )
    assert claimed.status is AgentInvocationStatus.RUNNING
    result = AgentResultSubmit(
        idempotency_key="curator-task-1",
        result={
            "candidate": {"result": {"items": []}, "state_updates": {}},
            "model_metadata": {},
            "prompt_version": "simulation_curator.worker.v1",
        },
    )
    completed = await services.agent_invocations.submit_result(
        invocation.id,
        result,
        role=AgentRole.SIMULATION_CURATOR,
    )
    duplicate = await services.agent_invocations.submit_result(
        invocation.id,
        result,
        role=AgentRole.SIMULATION_CURATOR,
    )
    assert completed.status is AgentInvocationStatus.COMPLETED
    assert duplicate.result_hash == completed.result_hash
    linked = await services.agent_invocations.attach_result_ref(
        invocation.id,
        "evt_provider_attempt",
    )
    assert linked.result_ref == "evt_provider_attempt"
    assert linked.result_payload is None
    global_page = await services.agent_invocations.list_all(limit=10)
    assert global_page.total == 1
    assert [item.id for item in global_page.items] == [invocation.id]


async def test_role_mcp_tool_sets_are_isolated(services: ServiceContainer) -> None:
    servers = create_role_mcp_servers(services)
    manager = {tool.name for tool in servers["manager"]._tool_manager.list_tools()}
    curator = {tool.name for tool in servers["curator"]._tool_manager.list_tools()}
    judge = {tool.name for tool in servers["judge"]._tool_manager.list_tools()}

    assert "submit_evaluation_plan" in manager
    assert "run_cases" not in manager
    assert "submit_curator_result" in curator
    assert "submit_judge_result" not in curator
    assert "submit_judge_result" in judge
    assert "submit_curator_result" not in judge
    assert curator == {
        "get_agent_invocation",
        "submit_curator_result",
        "fail_agent_invocation",
    }
    assert judge == {
        "get_agent_invocation",
        "submit_judge_result",
        "fail_agent_invocation",
    }


async def test_manager_shared_asset_mutation_requires_same_session_user_event(
    services: ServiceContainer,
) -> None:
    first = await services.assistant.create_session(
        AssistantSessionCreate(title="target approval"),
        created_by="user",
    )
    second = await services.assistant.create_session(
        AssistantSessionCreate(title="unrelated"),
        created_by="user",
    )
    approved = await services.assistant.send_message(
        first.id,
        AssistantMessageCreate(
            client_message_id="approve-target",
            content="确认创建这个 Target",
        ),
        actor_id="user",
    )
    unrelated = await services.assistant.send_message(
        second.id,
        AssistantMessageCreate(
            client_message_id="other-message",
            content="unrelated",
        ),
        actor_id="user",
    )
    manager = create_role_mcp_servers(services)["manager"]
    arguments = {
        "value": {
            "id": "target_manager_confirmed",
            "name": "Confirmed target",
            "driver_type": "openai_compatible",
            "endpoint": "https://agent.invalid/v1",
            "versions": [{"version": "v1"}],
        },
        "assistant_session_id": first.id,
        "confirmation_event_id": unrelated.event_id,
    }
    with pytest.raises(ToolError):
        await manager._tool_manager.call_tool("create_target", arguments)
    arguments["confirmation_event_id"] = approved.event_id
    created = await manager._tool_manager.call_tool("create_target", arguments)
    assert created["id"] == "target_manager_confirmed"
