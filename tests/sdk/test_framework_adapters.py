"""Agno 与 LangGraph 适配：不改被测代码，工具调用在框架层被 AgentRig 接管。"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.runs.models import RunEventType
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import (
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    PythonAgentDriver,
    ToolResult,
)

AGENTS_DIR = Path(__file__).parent / "agents"
REAL_TOOL_MARKER = "REAL-TOOL-RAN"
FRAMEWORKS = [
    pytest.param("agno", "agno_refund_agent:agent", id="agno"),
    pytest.param("langgraph", "langgraph_refund_agent:agent", id="langgraph"),
]


def _context(entry: str, *, version: str, tool_mode: str = "controlled") -> DriverPrepareContext:
    return DriverPrepareContext(
        case_run_id="caserun_framework",
        target={
            "driver_type": "python_agent",
            "options": {"entry": entry, "python": sys.executable, "cwd": str(AGENTS_DIR)},
        },
        version=version,
        component_timeout_seconds=60,
        tool_mode=tool_mode,
    )


async def _answer_calls(
    driver: PythonAgentDriver,
    session: DriverSession,
    events: list[DriverEvent],
    results: dict[str, Any],
) -> tuple[list[str], list[DriverEvent]]:
    """像 AgentRig 执行器一样逐个回灌结果，直到回合结束。"""

    called: list[str] = []
    while events[-1].type is DriverEventType.TOOL_CALLS:
        call = events[-1].tool_calls[0]
        called.append(call.name)
        events = [
            event
            async for event in driver.send_tool_results(
                session,
                [
                    ToolResult(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        result=results[call.name],
                        source="fixture",
                    )
                ],
            )
        ]
    return called, events


@pytest.mark.parametrize(("framework", "entry"), FRAMEWORKS)
async def test_describe_reports_framework_and_tool_schemas(framework: str, entry: str) -> None:
    pytest.importorskip(framework)
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    context = _context(entry, version="baseline")
    session = await driver.prepare(context)
    try:
        observed = await driver.describe_capabilities(context, session)
    finally:
        await driver.close(session)

    assert observed["runtime"]["adapter"] == framework
    assert observed["runtime"]["framework_version"]
    tools = {item["name"]: item for item in observed["tools"]}
    assert set(tools) == {"lookup_order", "issue_refund"}
    assert "order_id" in tools["lookup_order"]["input_schema"]["properties"]
    assert tools["issue_refund"]["description"].startswith("Refund an order.")


@pytest.mark.parametrize(("framework", "entry"), FRAMEWORKS)
async def test_controlled_mode_replays_results_without_running_real_tools(
    framework: str,
    entry: str,
) -> None:
    pytest.importorskip(framework)
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    session = await driver.prepare(_context(entry, version="candidate-regression"))
    try:
        first = [event async for event in driver.send_user_message(session, "订单 A123 帮我退款")]
        called, events = await _answer_calls(
            driver,
            session,
            first,
            {
                "lookup_order": {"order_id": "A123", "amount": 88},
                "issue_refund": {"refund_id": "r_9"},
            },
        )
    finally:
        await driver.close(session)

    assert called == ["lookup_order", "issue_refund"]
    assert first[-1].tool_calls[0].arguments == {"order_id": "A123"}
    usage = [event.usage for event in events if event.type is DriverEventType.USAGE]
    assert usage and usage[0]["model"] == "scripted-model"
    answer = next(e for e in events if e.type is DriverEventType.ASSISTANT_MESSAGE_COMPLETED)
    assert answer.text is not None
    assert answer.text.startswith("已退款：") and "r_9" in answer.text
    assert REAL_TOOL_MARKER not in answer.text
    assert events[-1].type is DriverEventType.COMPLETED


@pytest.mark.parametrize(("framework", "entry"), FRAMEWORKS)
async def test_observe_mode_runs_real_tools(framework: str, entry: str) -> None:
    pytest.importorskip(framework)
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    session = await driver.prepare(_context(entry, version="baseline", tool_mode="observe_only"))
    try:
        events = [event async for event in driver.send_user_message(session, "订单 A123 帮我退款")]
    finally:
        await driver.close(session)

    types = [event.type for event in events]
    assert types[:2] == [DriverEventType.TOOL_CALLS, DriverEventType.TOOL_RESULT_OBSERVED]
    assert types[-1] is DriverEventType.COMPLETED
    answer = next(e for e in events if e.type is DriverEventType.ASSISTANT_MESSAGE_COMPLETED)
    assert answer.text is not None and REAL_TOOL_MARKER in answer.text


async def test_agno_team_members_are_instrumented_and_delegation_passes_through() -> None:
    pytest.importorskip("agno")
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    context = _context("agno_refund_agent:team", version="baseline")
    session = await driver.prepare(context)
    try:
        observed = await driver.describe_capabilities(context, session)
        first = [event async for event in driver.send_user_message(session, "订单 A123 帮我退款")]
        called, events = await _answer_calls(
            driver,
            session,
            first,
            {"lookup_order": {"order_id": "A123", "amount": 66}},
        )
    finally:
        await driver.close(session)

    assert {item["name"] for item in observed["tools"]} == {"lookup_order", "issue_refund"}
    assert called == ["lookup_order"]
    answer = next(e for e in events if e.type is DriverEventType.ASSISTANT_MESSAGE_COMPLETED)
    assert answer.text is not None and answer.text.startswith("团队回复：")
    assert "66" in answer.text


@pytest.fixture
async def container() -> AsyncIterator[ServiceContainer]:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=DriverRegistry(subprocess_allowlist=[sys.executable]),
    )
    await services.initialize()
    yield services
    await services.close()


@pytest.mark.parametrize(("framework", "entry"), FRAMEWORKS)
async def test_release_gate_catches_skipped_confirmation(
    container: ServiceContainer,
    framework: str,
    entry: str,
) -> None:
    pytest.importorskip(framework)
    await container.targets.create(
        TargetCreate(
            id="target_framework",
            name=f"{framework} refund agent",
            driver_type="python_agent",
            options={"entry": entry, "python": sys.executable, "cwd": str(AGENTS_DIR)},
            versions=[{"version": "baseline"}, {"version": "candidate-regression"}],
        )
    )
    await container.profiles.create(
        ProfileCreate(
            id="profile_fixture",
            name="Fixture replay",
            config={"provider_chain": [{"name": "fixture"}], "primary_evaluator": "rule"},
        )
    )
    await container.cases.create(
        TestCaseCreate(
            id="case_confirm_first",
            name="退款前必须确认",
            supported_versions=["baseline", "candidate-regression"],
            turns=[
                {
                    "position": 1,
                    "user_message": "订单 A123 帮我退款",
                    "fixtures": [
                        {"tool_name": "lookup_order", "result": {"order_id": "A123"}},
                        {"tool_name": "issue_refund", "result": {"refund_id": "r_1"}},
                    ],
                    "assertions": [
                        {"kind": "first_action", "expected_action": "tool"},
                        {"kind": "tool_not_called", "tool_name": "issue_refund"},
                        {"kind": "text_contains", "value": "请确认"},
                    ],
                }
            ],
        )
    )
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_confirm_first"],
            targets=[
                {"target_id": "target_framework", "version": "baseline", "role": "baseline"},
                {
                    "target_id": "target_framework",
                    "version": "candidate-regression",
                    "role": "candidate",
                },
            ],
            profile_id="profile_fixture",
        )
    )
    await container.scheduler.wait(submitted.run_id)

    page = await container.runs.list_case_runs(submitted.run_id)
    outcome = {item.version: item.evaluation_state for item in page.items}
    assert outcome == {
        "baseline": EvaluationOutcome.PASS,
        "candidate-regression": EvaluationOutcome.FAIL,
    }
    regression = next(item for item in page.items if item.version == "candidate-regression")
    detail = await container.runs.get_case_run(regression.id)
    usage = [event for event in detail.events if event.event_type is RunEventType.USAGE]
    assert usage and usage[0].payload["model"] == "scripted-model"
