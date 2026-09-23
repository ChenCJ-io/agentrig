"""python_agent Driver 与 harness 进程之间的 JSONL 协议。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from agentrig.targets.drivers import (
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    PythonAgentDriver,
    ToolResult,
)

AGENTS_DIR = Path(__file__).parent / "agents"


def _context(
    entry: str = "refund_agent:run",
    *,
    python: str = sys.executable,
    version: str | None = "baseline",
    tool_mode: str = "controlled",
    **options: Any,
) -> DriverPrepareContext:
    return DriverPrepareContext(
        case_run_id="caserun_sdk",
        target={
            "id": "target_python_agent",
            "driver_type": "python_agent",
            "options": {"entry": entry, "python": python, "cwd": str(AGENTS_DIR), **options},
        },
        version=version,
        component_timeout_seconds=30,
        tool_mode=tool_mode,
    )


def _result(call_id: str, name: str, value: Any) -> ToolResult:
    return ToolResult(tool_call_id=call_id, tool_name=name, result=value, source="fixture")


async def test_describe_reports_runtime_and_decorated_tools() -> None:
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    context = _context()
    session = await driver.prepare(context)
    try:
        observed = await driver.describe_capabilities(context, session)
    finally:
        await driver.close(session)

    assert observed["source_status"] == "observed"
    assert observed["runtime"]["adapter"] == "callable"
    assert observed["runtime"]["protocol"] == "agentrig_harness"
    tools = {item["name"]: item for item in observed["tools"]}
    assert set(tools) == {"lookup_order", "issue_refund"}
    assert tools["lookup_order"]["input_schema"]["required"] == ["order_id"]


async def test_controlled_turns_inject_results_despite_agent_output_noise() -> None:
    """被测代码往 stdout/stderr 大量输出时，协议既不被污染也不因管道写满而卡死。"""

    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    session = await driver.prepare(_context())
    try:
        first = [event async for event in driver.send_user_message(session, "帮我退款")]
        assert [event.type for event in first] == [DriverEventType.TOOL_CALLS]
        call = first[0].tool_calls[0]
        assert (call.name, call.arguments) == ("lookup_order", {"order_id": "A123"})

        answer = [
            event
            async for event in driver.send_tool_results(
                session,
                [_result(call.id, call.name, {"order_id": "A123", "amount": 88})],
            )
        ]
        assert [event.type for event in answer] == [
            DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            DriverEventType.COMPLETED,
        ]
        assert answer[0].text == "订单 A123 金额 88，请确认是否退款"

        second = [event async for event in driver.send_user_message(session, "确认")]
        lookup = second[0].tool_calls[0]
        refund_events = [
            event
            async for event in driver.send_tool_results(
                session,
                [_result(lookup.id, lookup.name, {"order_id": "A123", "amount": 88})],
            )
        ]
        refund = refund_events[0].tool_calls[0]
        assert (refund.name, refund.arguments) == (
            "issue_refund",
            {"order_id": "A123", "amount": 88},
        )
        final = [
            event
            async for event in driver.send_tool_results(
                session,
                [_result(refund.id, refund.name, {"refund_id": "r_1"})],
            )
        ]
        assert final[0].text == '已退款：{"refund_id": "r_1"}'
    finally:
        await driver.close(session)


async def test_observe_mode_runs_real_tools_and_keeps_only_result_digests() -> None:
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    session = await driver.prepare(
        _context(version="candidate-regression", tool_mode="observe_only")
    )
    try:
        events = [event async for event in driver.send_user_message(session, "帮我退款")]
    finally:
        await driver.close(session)

    assert [event.type for event in events] == [
        DriverEventType.TOOL_CALLS,
        DriverEventType.TOOL_RESULT_OBSERVED,
        DriverEventType.TOOL_CALLS,
        DriverEventType.TOOL_RESULT_OBSERVED,
        DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
        DriverEventType.COMPLETED,
    ]
    observed = events[1].payload
    assert observed["tool_name"] == "lookup_order"
    assert observed["result_exported"] is False
    assert len(observed["result_sha256"]) == 64
    assert "result" not in observed
    assert events[4].text == "已退款：real refund issued for A123 (199)"


async def test_startup_failure_is_reported_instead_of_a_silent_exit() -> None:
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    context = _context("broken_agent:run")

    with pytest.raises(RuntimeError, match="agent configuration is missing"):
        await driver.probe(context)

    session = await driver.prepare(context)
    try:
        events = [event async for event in driver.send_user_message(session, "hi")]
    finally:
        await driver.close(session)
    assert events[0].type is DriverEventType.ERROR
    assert "harness startup failed: RuntimeError" in str(events[0].error)


async def test_interpreter_must_be_allowlisted_and_options_are_strict() -> None:
    driver = PythonAgentDriver(executable_allowlist=[])
    with pytest.raises(PermissionError, match="subprocess_allowlist"):
        driver.validate_configuration(
            _context().target["options"],
            secret_configured=False,
        )

    allowed = PythonAgentDriver(executable_allowlist=[sys.executable])
    with pytest.raises(ValueError, match="credential_env"):
        allowed.validate_configuration(
            _context().target["options"],
            secret_configured=True,
        )
    with pytest.raises(ValueError, match="entry"):
        allowed.validate_configuration(
            {**_context().target["options"], "entry": "no_colon"},
            secret_configured=False,
        )


def test_registry_describes_python_agent_options() -> None:
    registry = DriverRegistry(subprocess_allowlist=[sys.executable])

    described = {item["driver_type"]: item for item in registry.descriptions()}
    schema = registry.configuration_schema("python_agent")

    assert described["python_agent"]["deployment_ready"] is True
    assert described["python_agent"]["options_schema_available"] is True
    assert schema is not None and schema["required"] == ["entry", "python"]
    assert registry.configuration_example("python_agent") is not None


@pytest.mark.skipif(shutil.which("python3.10") is None, reason="python3.10 is not installed")
async def test_harness_runs_on_python_310_without_installing_agentrig() -> None:
    interpreter = str(shutil.which("python3.10"))
    driver = PythonAgentDriver(executable_allowlist=[interpreter])
    context = _context(python=interpreter)
    session = await driver.prepare(context)
    try:
        observed = await driver.describe_capabilities(context, session)
        events = [event async for event in driver.send_user_message(session, "帮我退款")]
    finally:
        await driver.close(session)

    assert observed["runtime"]["python_version"].startswith("3.10.")
    assert events[0].tool_calls[0].name == "lookup_order"


async def test_agent_process_gets_a_trimmed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST_SECRET", "must-not-leak")
    monkeypatch.setenv("FORWARDED_VAR", "forwarded")
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])
    context = _context(
        "env_agent:run",
        inherit_env=["FORWARDED_VAR"],
        env={"EXPLICIT_VAR": "explicit"},
        credential_env="MODEL_KEY",
    )
    context.secret_value = "resolved-secret"
    session = await driver.prepare(context)
    try:
        events = [event async for event in driver.send_user_message(session, "env")]
    finally:
        await driver.close(session)

    assert json.loads(str(events[0].text)) == {
        "HOST_SECRET": None,
        "FORWARDED_VAR": "forwarded",
        "EXPLICIT_VAR": "explicit",
        "MODEL_KEY": "resolved-secret",
    }


def test_conversation_initial_state_is_accepted_for_direct_chat() -> None:
    driver = PythonAgentDriver(executable_allowlist=[sys.executable])

    driver.validate_configuration(
        {
            **_context().target["options"],
            "conversation_initial_state": {"world": "photo retouching app"},
        },
        secret_configured=False,
    )
