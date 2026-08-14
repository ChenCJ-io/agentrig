"""Capability evidence and AG-UI normalization remain safe and deterministic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from agentrig.capabilities import (
    CapabilityComparisonPolicy,
    TargetCapabilitySnapshot,
    build_declared_snapshot,
    build_legacy_snapshot,
    compare_capabilities,
    merge_observed_capabilities,
)
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.evaluations.models import EvaluationOutcome, EvaluatorType
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.repositories.runs import SqlRunRepository
from agentrig.projects import ProjectService
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.targets.drivers import (
    AgentScopeDriver,
    AgUiDriver,
    DriverCapabilities,
    DriverEventType,
    DriverPrepareContext,
)

pytestmark = pytest.mark.asyncio


def _declared_snapshot(
    *,
    tool_schema: dict[str, Any] | None = None,
    collected_at: datetime | None = None,
) -> TargetCapabilitySnapshot:
    return build_declared_snapshot(
        case_run_id="case_run_capability",
        target={
            "id": "target_agentscope",
            "driver_type": "agentscope",
            "version": "2.0.6",
            "options": {
                "framework_version": "2.0.6",
                "request_headers": {"Authorization": "Bearer top-secret"},
                "tool_catalog": [
                    {
                        "name": "lookup",
                        "description": "Find a record",
                        "input_schema": tool_schema
                        or {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                    {"name": "audit", "input_schema": {"type": "object"}},
                ],
                "memory": {
                    "scope": "session",
                    "content": "top-secret memory body",
                },
                "workspace": {
                    "isolation": "per-run",
                    "body": "top-secret artifact body",
                },
                "collaboration": {
                    "team_mode": "nested",
                    "messages": ["top-secret child message"],
                },
            },
        },
        profile={"tool_mode": "controlled", "provider_chain": []},
        driver_capabilities=DriverCapabilities(
            streaming=True,
            tool_call_observation=True,
            permission_observation=True,
        ),
        collected_at=collected_at,
    )


def _observed(
    snapshot: TargetCapabilitySnapshot,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> TargetCapabilitySnapshot:
    return merge_observed_capabilities(
        snapshot,
        {
            "source_status": "observed",
            "runtime": {
                "framework": "agentscope",
                "framework_version": "2.0.6",
            },
            "tools": tools
            or [
                {"name": "audit", "input_schema": {"type": "object"}},
                {
                    "name": "lookup",
                    "description": "Find a record",
                    "input_schema": {
                        "properties": {"query": {"type": "string"}},
                        "type": "object",
                    },
                },
            ],
            "features": {
                "streaming": {"status": "observed", "value": True},
                "permission_observation": {
                    "status": "observed",
                    "value": True,
                },
            },
            "memory": {
                "scope": "session",
                "content": "top-secret observed memory",
            },
        },
    )


async def test_capability_hash_is_stable_redacted_and_policy_aware() -> None:
    first = _declared_snapshot(
        collected_at=datetime(2026, 8, 10, 1, tzinfo=timezone.utc)
    )
    second = _declared_snapshot(
        collected_at=datetime(2026, 8, 10, 2, tzinfo=timezone.utc)
    )
    assert first.collection_status == "partial"
    assert first.snapshot_hash == second.snapshot_hash

    first_observed = _observed(first)
    second_observed = _observed(second)
    assert first_observed.collection_status == "complete"
    assert first_observed.snapshot_hash == second_observed.snapshot_hash
    serialized = first_observed.model_dump_json().casefold()
    assert "top-secret" not in serialized
    assert "authorization" not in serialized
    assert "memory body" not in serialized
    assert "find a record" not in serialized

    changed = _observed(
        _declared_snapshot(tool_schema={"type": "object"}),
        tools=[
            {
                "name": "lookup",
                "input_schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
            }
        ],
    )
    blocked = compare_capabilities(first_observed, changed)
    assert blocked.comparison == "incomparable_environment"
    assert blocked.differences[0].path == "tools"

    allowed = compare_capabilities(
        first_observed,
        changed,
        CapabilityComparisonPolicy(allowed_differences=["tools.*"]),
    )
    assert allowed.comparison == "warning_difference"
    assert allowed.differences[0].allowed is True

    partial = compare_capabilities(first, first)
    legacy = compare_capabilities(
        build_legacy_snapshot(case_run_id="old-a", target={}),
        build_legacy_snapshot(case_run_id="old-b", target={}),
    )
    assert partial.comparison == "incomparable_environment"
    assert legacy.comparison == "incomparable_environment"


async def test_agentscope_agui_probe_and_stream_are_ordered_and_body_free() -> None:
    captured: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "authorization": request.headers.get("authorization"),
                "body": json.loads((await request.aread()) or b"{}"),
            }
        )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "version": "2.0.6",
                    "runtime": {"protocol_version": "1"},
                    "features": {
                        "permission_observation": {
                            "status": "observed",
                            "value": True,
                        }
                    },
                },
            )
        raw_events = [
            {
                "type": "RUN_STARTED",
                "eventId": "event-1",
                "sequence": 1,
                "threadId": "thread-1",
                "runId": "run-1",
            },
            {
                "type": "AGENT_STARTED",
                "eventId": "event-2",
                "sequence": 2,
                "agentPath": ["root", "researcher"],
                "content": "top-secret agent body",
            },
            {
                "type": "REASONING_MESSAGE_CONTENT",
                "eventId": "event-3",
                "sequence": 3,
                "delta": "top-secret chain of thought",
                "agentPath": ["root", "researcher"],
            },
            {
                "type": "TOOL_CALL_RESULT",
                "eventId": "event-4",
                "sequence": 4,
                "toolCallId": "call-1",
                "toolCallName": "lookup",
                "result": {"secret": "top-secret tool body"},
            },
            {
                "type": "USAGE_SNAPSHOT",
                "eventId": "event-5",
                "sequence": 5,
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
            {
                "type": "PERMISSION_REQUESTED",
                "eventId": "event-6",
                "sequence": 6,
                "permissionId": "permission-1",
                "authorization": "top-secret",
                "metadata": {"cookie": "top-secret", "risk": "high"},
            },
            {
                "type": "PERMISSION_REQUESTED",
                "eventId": "event-6",
                "sequence": 6,
            },
            {
                "type": "DATA_PART",
                "eventId": "late-event",
                "sequence": 2,
                "content": "top-secret late body",
            },
            {
                "type": "RUN_FINISHED",
                "eventId": "event-7",
                "sequence": 7,
            },
        ]
        body = "".join(
            f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            for item in raw_events
        )
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    driver = AgentScopeDriver(transport=httpx.MockTransport(handler))
    context = DriverPrepareContext(
        case_run_id="case_run_agentscope",
        target={
            "endpoint": "https://agentscope.invalid",
            "options": {
                "run_path": "/agui",
                "capability_path": "/capabilities",
            },
        },
        version="2.0.6",
        initial_state={},
        secret_value="top-secret",
        component_timeout_seconds=2,
    )
    session = await driver.prepare(context)
    capability = await driver.describe_capabilities(context, session)
    events = [event async for event in driver.send_user_message(session, "hello")]
    permission_events = [
        event
        async for event in driver.submit_permission_response(
            session,
            {"permission_id": "permission-1", "decision": "deny"},
        )
    ]

    assert capability["source_status"] == "observed"
    assert capability["runtime"]["framework"] == "agentscope"
    assert capability["runtime"]["framework_version"] == "2.0.6"
    assert [item.type for item in events] == [
        DriverEventType.SESSION_STARTED,
        DriverEventType.AGENT_STARTED,
        DriverEventType.THINKING_DELTA,
        DriverEventType.TOOL_RESULT_OBSERVED,
        DriverEventType.USAGE,
        DriverEventType.PERMISSION_REQUESTED,
        DriverEventType.COMPLETED,
    ]
    assert events[1].agent_path == ["root", "researcher"]
    assert events[2].payload.get("delta") is None
    assert events[3].payload["result_exported"] is False
    assert "result" not in events[3].payload
    assert events[4].usage == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert events[5].payload["metadata"] == {"risk": "high"}
    assert "top-secret" not in json.dumps(
        [item.model_dump(mode="json") for item in events],
        ensure_ascii=False,
    )
    assert [(item["method"], item["path"]) for item in captured] == [
        ("GET", "/capabilities"),
        ("POST", "/agui"),
        ("POST", "/agui"),
    ]
    assert all(item["authorization"] == "Bearer top-secret" for item in captured)
    assert "top-secret" not in json.dumps(captured[1]["body"], ensure_ascii=False)
    assert permission_events == []
    assert captured[2]["body"]["forwardedProps"] == {
        "agentrig_permission_response": {
            "permission_id": "permission-1",
            "decision": "deny",
        }
    }


async def test_agui_reconnect_resumes_cursor_without_duplicate_events() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "last_event_id": request.headers.get("last-event-id"),
                "body": json.loads(await request.aread()),
            }
        )
        started = {
            "type": "RUN_STARTED",
            "eventId": "event-1",
            "sequence": 1,
            "threadId": "thread-1",
            "runId": "run-1",
        }
        values = (
            [started]
            if len(requests) == 1
            else [
                started,
                {
                    "type": "RUN_FINISHED",
                    "eventId": "event-2",
                    "sequence": 2,
                },
            ]
        )
        body = "".join(f"data: {json.dumps(item)}\n\n" for item in values)
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    driver = AgUiDriver(transport=httpx.MockTransport(handler))
    session = await driver.prepare(
        DriverPrepareContext(
            case_run_id="case_run_reconnect",
            target={
                "endpoint": "https://agui.invalid",
                "options": {"run_path": "/run", "max_reconnects": 1},
            },
            version="1",
            component_timeout_seconds=2,
        )
    )
    events = [event async for event in driver.send_user_message(session, "hello")]

    assert [item.type for item in events] == [
        DriverEventType.SESSION_STARTED,
        DriverEventType.COMPLETED,
    ]
    assert len(requests) == 2
    assert requests[1]["last_event_id"] == "event-1"
    assert requests[1]["body"]["runId"] == "run-1"
    assert requests[1]["body"]["forwardedProps"]["agentrig_cursor"] == {
        "event_id": "event-1",
        "sequence": 1,
    }


async def test_capability_snapshot_freezes_after_first_runtime_event() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    await ProjectService(database).ensure_default()
    repository = SqlRunRepository(database)
    declared = _declared_snapshot()
    observed = _observed(declared)
    try:
        await repository.create_run(
            run_id="run_capability_freeze",
            selection_snapshot={},
            resolved_case_ids=["case_capability"],
            profile_snapshot={},
            target_snapshots=[],
        )
        await repository.create_case_run(
            case_run_id="case_run_capability",
            run_id="run_capability_freeze",
            case_id="case_capability",
            case_snapshot={},
            target_snapshot={"id": "target_agentscope"},
            profile_snapshot={},
            capability_snapshot=declared,
            version="2.0.6",
            repeat_index=0,
            comparison_pair_id=None,
            comparison_role=None,
            status=CaseRunStatus.QUEUED,
            primary_evaluator=EvaluatorType.RULE,
            evaluation_state=EvaluationOutcome.INCONCLUSIVE,
        )
        await repository.set_capability_snapshot("case_run_capability", observed)
        await repository.append_event(
            "case_run_capability",
            RunEventType.CAPABILITY_SNAPSHOT,
            {"snapshot_hash": observed.snapshot_hash},
        )
        with pytest.raises(AgentRigError) as caught:
            await repository.set_capability_snapshot("case_run_capability", observed)
        assert caught.value.detail.code is ErrorCode.CONFLICT
    finally:
        await database.dispose()
