"""AgentRig → ACP → Goose → CaseRun MCP Proxy 的真实兼容性测试。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import uvicorn

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets import TargetCreate
from agentrig.tool_results import SampleCreate
from agentrig.tool_results.models import SampleStatus

GOOSE_ROOT_VALUE = os.environ.get("AGENTRIG_TEST_GOOSE_ROOT")
GOOSE_ROOT = (
    Path(GOOSE_ROOT_VALUE).expanduser().resolve()
    if GOOSE_ROOT_VALUE
    else Path.cwd()
)
GOOSE_ACP_COMMAND = GOOSE_ROOT / ".runtime" / "run-acp.sh"

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTRIG_TEST_GOOSE_LIVE") != "1"
    or not os.environ.get("DEEPSEEK_API_KEY")
    or not GOOSE_ROOT_VALUE
    or not GOOSE_ACP_COMMAND.is_file(),
    reason=(
        "set AGENTRIG_TEST_GOOSE_LIVE=1, DEEPSEEK_API_KEY, and "
        "AGENTRIG_TEST_GOOSE_ROOT before running the live ACP test"
    ),
)


async def test_goose_uses_case_fixture_through_agentrig_proxy(
    unused_tcp_port: int,
) -> None:
    isolation_root = GOOSE_ROOT / ".runtime" / "agentrig-case-runtimes"
    services = ServiceContainer.build(
        Settings(
            server={"host": "0.0.0.0", "port": unused_tcp_port},
            proxy={
                "public_url": (
                    f"http://host.docker.internal:{unused_tcp_port}/proxy"
                )
            },
            execution={
                "subprocess_allowlist": [str(GOOSE_ACP_COMMAND)],
            },
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(services),
            host="0.0.0.0",
            port=unused_tcp_port,
            log_level="warning",
        )
    )
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        sample = await services.samples.create(
            SampleCreate(
                id="sample_usd_cny_rate",
                name="USD to CNY approved sample",
                tool_name="get_exchange_rate",
                match_arguments={"base": "USD", "quote": "CNY"},
                content={
                    "base": "USD",
                    "quote": "CNY",
                    "rate": 7.25,
                    "source": "sample",
                },
                supported_versions=["deepseek-v4-flash"],
            )
        )
        sample = await services.samples.review(
            sample.id,
            SampleStatus.APPROVED,
        )
        assert sample.status is SampleStatus.APPROVED

        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_goose_weather_fixture",
                    "name": "Goose ACP Fixture Tool",
                    "supported_versions": ["deepseek-v4-flash"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": (
                                "Call the get_weather tool exactly once with "
                                '{"city":"Shanghai"}. Use its result, then reply '
                                "with exactly: WEATHER_OK city=Shanghai "
                                "temperature=26 source=fixture"
                            ),
                            "fixtures": [
                                {
                                    "tool_name": "get_weather",
                                    "match_arguments": {"city": "Shanghai"},
                                    "result": {
                                        "city": "Shanghai",
                                        "temperature": 26,
                                        "source": "fixture",
                                    },
                                }
                            ],
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "get_weather",
                                },
                                {
                                    "kind": "tool_arguments_equal",
                                    "tool_name": "get_weather",
                                    "expected_arguments": {"city": "Shanghai"},
                                },
                                {
                                    "kind": "text_contains",
                                    "value": (
                                        "WEATHER_OK city=Shanghai temperature=26 "
                                        "source=fixture"
                                    ),
                                },
                                {"kind": "no_execution_error"},
                            ],
                        }
                    ],
                }
            )
        )
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_goose_exchange_sample",
                    "name": "Goose ACP Approved Sample",
                    "supported_versions": ["deepseek-v4-flash"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": (
                                "Call get_exchange_rate exactly once with "
                                '{"base":"USD","quote":"CNY"}. Use its result, '
                                "then reply exactly: RATE_OK base=USD quote=CNY "
                                "rate=7.25 source=sample"
                            ),
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "get_exchange_rate",
                                },
                                {
                                    "kind": "tool_arguments_equal",
                                    "tool_name": "get_exchange_rate",
                                    "expected_arguments": {
                                        "base": "USD",
                                        "quote": "CNY",
                                    },
                                },
                                {
                                    "kind": "text_contains",
                                    "value": (
                                        "RATE_OK base=USD quote=CNY rate=7.25 "
                                        "source=sample"
                                    ),
                                },
                                {"kind": "no_execution_error"},
                            ],
                        }
                    ],
                }
            )
        )
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_goose_project_multiturn",
                    "name": "Goose ACP Multi-turn Fixture Tools",
                    "supported_versions": ["deepseek-v4-flash"],
                    "primary_evaluator": "rule",
                    "case_assertions": [
                        {
                            "kind": "tool_call_order",
                            "tool_names": ["get_project_list", "open_project"],
                        }
                    ],
                    "turns": [
                        {
                            "position": 1,
                            "user_message": (
                                "Call get_project_list exactly once with no "
                                "arguments. Use its result, then reply exactly: "
                                "LIST_OK first_project_id=430409687"
                            ),
                            "fixtures": [
                                {
                                    "tool_name": "get_project_list",
                                    "match_arguments": {},
                                    "result": {
                                        "projects": [
                                            {
                                                "project_id": 430409687,
                                                "name": "Fixture Project",
                                            }
                                        ]
                                    },
                                }
                            ],
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "get_project_list",
                                },
                                {
                                    "kind": "text_contains",
                                    "value": "LIST_OK first_project_id=430409687",
                                },
                            ],
                        },
                        {
                            "position": 2,
                            "user_message": (
                                "Use the project_id from the previous tool result. "
                                "Call open_project exactly once with that project_id, "
                                "then reply exactly: OPEN_OK project_id=430409687"
                            ),
                            "fixtures": [
                                {
                                    "tool_name": "open_project",
                                    "match_arguments": {
                                        "project_id": 430409687
                                    },
                                    "result": {
                                        "opened": True,
                                        "project_id": 430409687,
                                    },
                                }
                            ],
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "open_project",
                                },
                                {
                                    "kind": "tool_arguments_equal",
                                    "tool_name": "open_project",
                                    "expected_arguments": {
                                        "project_id": 430409687
                                    },
                                },
                                {
                                    "kind": "text_contains",
                                    "value": "OPEN_OK project_id=430409687",
                                },
                                {"kind": "no_execution_error"},
                            ],
                        },
                    ],
                }
            )
        )
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_goose_acp",
                    "name": "Goose ACP / DeepSeek V4 Flash",
                    "driver_type": "acp",
                    "secret_ref": "env:DEEPSEEK_API_KEY",
                    "options": {
                        "command": [str(GOOSE_ACP_COMMAND)],
                        "cwd": str(GOOSE_ROOT),
                        "session_cwd": "/workspace",
                        "credential_env": "DEEPSEEK_API_KEY",
                        "env": {
                            "GOOSE_PROVIDER": "custom_deepseek",
                            "GOOSE_MODEL": "deepseek-v4-flash",
                        },
                        "tool_catalog": [
                            {
                                "name": "get_exchange_rate",
                                "description": (
                                    "Get the exchange rate between two currencies"
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "base": {"type": "string"},
                                        "quote": {"type": "string"},
                                    },
                                    "required": ["base", "quote"],
                                    "additionalProperties": False,
                                },
                                "outputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "base": {"type": "string"},
                                        "quote": {"type": "string"},
                                        "rate": {"type": "number"},
                                        "source": {"type": "string"},
                                    },
                                    "required": [
                                        "base",
                                        "quote",
                                        "rate",
                                        "source",
                                    ],
                                },
                            }
                        ],
                        "permission_mode": "allow_once",
                        "mcp_server_name": "agentrig-case-tools",
                        "isolation_root": str(isolation_root),
                        "isolation_env": "GOOSE_RUNTIME_DIR",
                        "shutdown_timeout_seconds": 2,
                    },
                    "versions": [{"version": "deepseek-v4-flash"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_goose_proxy_fixture",
                    "name": "Goose Proxy Fixture Rule",
                    "config": {
                        "tool_mode": "proxy",
                        "provider_chain": [
                            {"name": "fixture"},
                            {"name": "sample"},
                        ],
                        "primary_evaluator": "rule",
                        "concurrency": 3,
                        "case_timeout_seconds": 60,
                        "component_timeouts": {
                            "driver": 30,
                            "real_tool": 30,
                            "curator": 30,
                            "judge": 30,
                        },
                    },
                }
            )
        )

        submitted = await services.runs.run_cases(
            RunCasesRequest.model_validate(
                {
                    "case_ids": [
                        "case_goose_weather_fixture",
                        "case_goose_project_multiturn",
                        "case_goose_exchange_sample",
                    ],
                    "targets": [{"target_id": "target_goose_acp"}],
                    "profile_id": "profile_goose_proxy_fixture",
                }
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        assert len(page.items) == 3
        details = {
            item.case_id: await services.runs.get_case_run(item.id)
            for item in page.items
        }
        weather = details["case_goose_weather_fixture"]
        project = details["case_goose_project_multiturn"]
        exchange = details["case_goose_exchange_sample"]
        assert all(
            detail.status is CaseRunStatus.COMPLETED
            and detail.evaluation_state == "pass"
            for detail in details.values()
        )
        assert weather.summary["tool_call_count"] == 1
        assert project.summary["tool_call_count"] == 2
        assert exchange.summary["tool_call_count"] == 1
        assert services.proxy_scopes.active_count() == 0
        started = [item.started_at for item in page.items]
        assert all(value is not None for value in started)
        resolved_started = [value for value in started if value is not None]
        start_delta = (max(resolved_started) - min(resolved_started)).total_seconds()
        assert start_delta < 0.5

        for detail in details.values():
            event_types = [event.event_type for event in detail.events]
            for required in {
                RunEventType.USER_MESSAGE,
                RunEventType.DRIVER_REQUEST,
                RunEventType.DRIVER_SESSION,
                RunEventType.TOOL_CALL,
                RunEventType.PROVIDER_ATTEMPT,
                RunEventType.VALIDATION,
                RunEventType.TOOL_RESULT,
                RunEventType.ASSISTANT_TEXT,
                RunEventType.ASSISTANT_MESSAGE,
                RunEventType.USAGE,
            }:
                assert required in event_types
            turn_positions = {
                int(event.payload["turn_position"])
                for event in detail.events
                if "turn_position" in event.payload
            }
            for position in turn_positions:
                request_events = [
                    event
                    for event in detail.events
                    if event.event_type is RunEventType.DRIVER_REQUEST
                    and event.payload.get("turn_position") == position
                ]
                tool_calls = [
                    event
                    for event in detail.events
                    if event.event_type is RunEventType.TOOL_CALL
                    and event.payload.get("turn_position") == position
                ]
                tool_results = [
                    event
                    for event in detail.events
                    if event.event_type is RunEventType.TOOL_RESULT
                    and event.payload.get("turn_position") == position
                ]
                assert request_events[0].payload["phase"] == "started"
                assert request_events[-1].payload["phase"] == "completed"
                assert request_events[0].seq < tool_calls[0].seq
                assert (
                    tool_calls[-1].seq
                    < tool_results[-1].seq
                    < request_events[-1].seq
                )

        weather_call = next(
            event
            for event in weather.events
            if event.event_type is RunEventType.TOOL_CALL
        )
        weather_result = next(
            event
            for event in weather.events
            if event.event_type is RunEventType.TOOL_RESULT
        )
        assert weather_call.payload["via"] == "mcp_proxy"
        assert weather_call.payload["arguments"] == {"city": "Shanghai"}
        assert weather_result.payload["source"] == "fixture"
        assert weather_result.payload["result"] == {
            "city": "Shanghai",
            "temperature": 26,
            "source": "fixture",
        }
        project_calls = [
            event
            for event in project.events
            if event.event_type is RunEventType.TOOL_CALL
        ]
        assert [event.payload["tool_name"] for event in project_calls] == [
            "get_project_list",
            "open_project",
        ]
        assert project_calls[-1].payload["arguments"] == {
            "project_id": 430409687
        }
        project_sessions = {
            event.payload["session_id"]
            for event in project.events
            if event.event_type is RunEventType.ASSISTANT_MESSAGE
        }
        assert len(project_sessions) == 1
        exchange_result = next(
            event
            for event in exchange.events
            if event.event_type is RunEventType.TOOL_RESULT
        )
        assert exchange_result.payload["source"] == "sample"
        assert exchange_result.payload["metadata"]["sample_id"] == (
            "sample_usd_cny_rate"
        )
        exchange_attempts = [
            event.payload["status"]
            for event in exchange.events
            if event.event_type is RunEventType.PROVIDER_ATTEMPT
        ]
        assert exchange_attempts == ["miss", "hit"]
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=10)

    if isolation_root.exists():
        assert list(isolation_root.iterdir()) == []
