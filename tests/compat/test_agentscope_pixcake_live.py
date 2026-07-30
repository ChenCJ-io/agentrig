"""当前 AgentScope/Pixcake 的可选真实兼容性测试。

默认跳过，避免普通单元测试调用真实模型。显式设置
``AGENTRIG_TEST_PIXCAKE_URL=http://127.0.0.1:8000`` 后运行。

用例来自 2026-07-30 时 AgentScope 已审核资产：
- tc_from_error_099：单轮 apply_image_prompt；
- tc_from_error_080：两轮 apply_image_prompt → rollback_to_tool_call；
- tc_from_error_081：同一轮 get_project_list → open_project。
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.runs.schemas import CaseRunDetail, RunCasesRequest
from agentrig.targets import TargetCreate

PIXCAKE_URL = os.environ.get("AGENTRIG_TEST_PIXCAKE_URL")
pytestmark = pytest.mark.skipif(
    not PIXCAKE_URL,
    reason="AGENTRIG_TEST_PIXCAKE_URL is not configured",
)


def _pixcake_request(project_id: int, seed_path: str) -> dict[str, Any]:
    return {
        "pixcake_request": {
            "attachments": [
                {
                    "type": "image",
                    "image_id": "1",
                    "file_path": seed_path,
                }
            ],
            "metadata": {"project_id": str(project_id)},
        }
    }


async def _execute(
    case: TestCaseCreate,
    *,
    app_version: str,
    tool_version: int,
) -> CaseRunDetail:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        await services.cases.create(case)
        await services.targets.create(
            TargetCreate(
                id="target_agentscope_pixcake_live",
                name="AgentScope Pixcake Live",
                driver_type="pixcake_http_sse",
                endpoint=PIXCAKE_URL,
                options={
                    "user_id": 1045931,
                    "device_info": {
                        "device_id": "C22A0FE4-26D1-5BB8-A8F4-2130A7B185F5",
                        "os": "macOS",
                        "os_version": "15.7",
                        "app_version": "base-version",
                        "tool_version": 0,
                        "tool_version_branch": None,
                        "app_build": "65",
                    },
                    "chat_channel": "pixcake_client",
                },
                versions=[
                    {
                        "version": app_version,
                        "options": {
                            "device_info": {
                                "app_version": app_version,
                                "tool_version": tool_version,
                            }
                        },
                    }
                ],
            )
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_agentscope_controlled_live",
                name="AgentScope controlled live",
                config={
                    "tool_mode": "controlled",
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                    "case_timeout_seconds": 180,
                    "component_timeouts": {
                        "driver": 120,
                        "real_tool": 60,
                        "curator": 30,
                        "judge": 60,
                    },
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=[case.id or ""],
                targets=[
                    {
                        "target_id": "target_agentscope_pixcake_live",
                        "version": app_version,
                    }
                ],
                profile_id="profile_agentscope_controlled_live",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        return await services.runs.get_case_run(page.items[0].id)
    finally:
        await services.close()


def _assert_driver_evidence_is_correlated(detail: CaseRunDetail) -> None:
    request_events = [
        event
        for event in detail.events
        if event.event_type is RunEventType.DRIVER_REQUEST
    ]
    started = [
        event for event in request_events if event.payload["phase"] == "started"
    ]
    completed = [
        event for event in request_events if event.payload["phase"] == "completed"
    ]
    assert started
    assert len(started) == len(completed)
    started_ids = {event.payload["request_id"] for event in started}
    assert started_ids == {event.payload["request_id"] for event in completed}
    assert all(event.payload["duration_ms"] >= 0 for event in completed)
    assert any(
        event.event_type is RunEventType.DRIVER_SESSION
        and event.payload["session_id"]
        for event in detail.events
    )
    tool_calls = [
        event
        for event in detail.events
        if event.event_type is RunEventType.TOOL_CALL
    ]
    assert tool_calls
    assert all(event.payload["request_id"] in started_ids for event in tool_calls)

    messages = [
        event
        for event in detail.events
        if event.event_type is RunEventType.ASSISTANT_MESSAGE
    ]
    segments = [
        event
        for event in detail.events
        if event.event_type is RunEventType.ASSISTANT_TEXT
    ]
    assert len(messages) == len(detail.case_snapshot["turns"])
    assert segments
    for message in messages:
        position = message.payload["turn_position"]
        candidates = sorted(
            [
                event
                for event in [*segments, *tool_calls]
                if event.payload["turn_position"] == position
            ],
            key=lambda event: event.seq,
        )
        expected = message.payload.get("first_action")
        if expected and candidates:
            actual = (
                "tool"
                if candidates[0].event_type is RunEventType.TOOL_CALL
                else "refuse"
                if candidates[0].payload.get("refusal")
                else "text"
            )
            assert actual == expected


async def test_agentscope_single_tool_case_runs_through_agentrig() -> None:
    detail = await _execute(
        TestCaseCreate(
            id="compat_tc_from_error_099",
            name="AgentScope tc_from_error_099 compatibility",
            supported_versions=["9.2.0"],
            primary_evaluator="rule",
            initial_state=_pixcake_request(1698494, "seed://scene_bg.jpg"),
            turns=[
                {
                    "position": 1,
                    "user_message": "把背景增强一下，层次感好一点",
                    "fixtures": [
                        {
                            "tool_name": "apply_image_prompt",
                            "result": [
                                {"image_id": 1, "success": True, "record_id": 1}
                            ],
                        }
                    ],
                    "assertions": [
                        {
                            "kind": "tool_called",
                            "tool_name": "apply_image_prompt",
                        },
                        {"kind": "no_execution_error"},
                    ],
                }
            ],
        ),
        app_version="9.2.0",
        tool_version=4,
    )

    assert detail.status is CaseRunStatus.COMPLETED
    assert detail.evaluation_state is EvaluationOutcome.PASS
    _assert_driver_evidence_is_correlated(detail)
    assert any(
        event.event_type is RunEventType.TOOL_RESULT
        and event.payload["tool_name"] == "apply_image_prompt"
        and event.payload["source"] == "fixture"
        for event in detail.events
    )


async def test_agentscope_multiturn_rollback_case_runs_through_agentrig() -> None:
    detail = await _execute(
        TestCaseCreate(
            id="compat_tc_from_error_080",
            name="AgentScope tc_from_error_080 compatibility",
            supported_versions=["9.3.0"],
            primary_evaluator="rule",
            initial_state=_pixcake_request(2059895, "seed://portrait.jpg"),
            case_assertions=[
                {
                    "kind": "tool_call_order",
                    "tool_names": [
                        "apply_image_prompt",
                        "rollback_to_tool_call",
                    ],
                },
                {"kind": "no_execution_error"},
            ],
            turns=[
                {
                    "position": 1,
                    "user_message": "帮我把这张图调亮一点",
                    "fixtures": [
                        {
                            "tool_name": "apply_image_prompt",
                            "result": [
                                {"image_id": 1, "success": True, "record_id": 1}
                            ],
                        }
                    ],
                    "assertions": [
                        {
                            "kind": "tool_called",
                            "tool_name": "apply_image_prompt",
                        }
                    ],
                },
                {
                    "position": 2,
                    "user_message": "撤销刚才的修改",
                    "fixtures": [
                        {
                            "tool_name": "rollback_to_tool_call",
                            "result": {
                                "message": "已撤销最近一次修图",
                                "status": "success",
                            },
                        }
                    ],
                    "assertions": [
                        {
                            "kind": "tool_called",
                            "tool_name": "rollback_to_tool_call",
                        }
                    ],
                },
            ],
        ),
        app_version="9.3.0",
        tool_version=5,
    )

    assert detail.status is CaseRunStatus.COMPLETED
    assert detail.evaluation_state is EvaluationOutcome.PASS
    _assert_driver_evidence_is_correlated(detail)
    calls = [
        event.payload["tool_name"]
        for event in detail.events
        if event.event_type is RunEventType.TOOL_CALL
    ]
    assert calls == ["apply_image_prompt", "rollback_to_tool_call"]


async def test_agentscope_same_turn_tool_chain_runs_through_agentrig() -> None:
    detail = await _execute(
        TestCaseCreate(
            id="compat_tc_from_error_081",
            name="AgentScope tc_from_error_081 compatibility",
            supported_versions=["9.3.0"],
            primary_evaluator="rule",
            case_assertions=[
                {
                    "kind": "tool_call_order",
                    "tool_names": ["get_project_list", "open_project"],
                },
                {
                    "kind": "tool_arguments_equal",
                    "tool_name": "open_project",
                    "expected_arguments": {"project_id": 430409687},
                },
                {"kind": "no_execution_error"},
            ],
            turns=[
                {
                    "position": 1,
                    "user_message": "帮我打开换滤镜项目",
                    "fixtures": [
                        {
                            "tool_name": "get_project_list",
                            "result": {
                                "meta": {"total": 2},
                                "data": [
                                    {
                                        "id": 430409687,
                                        "name": "换滤镜项目",
                                        "image_count": 89,
                                    },
                                    {
                                        "id": 430409670,
                                        "name": "换背景项目",
                                        "image_count": 89,
                                    },
                                ],
                                "status": "success",
                                "message": "成功获取 2 个项目。",
                            },
                        },
                        {
                            "tool_name": "open_project",
                            "match_arguments": {"project_id": 430409687},
                            "result": {
                                "id": 430409687,
                                "status": "success",
                                "message": "项目已成功打开",
                            },
                        },
                    ],
                }
            ],
        ),
        app_version="9.3.0",
        tool_version=5,
    )

    assert detail.status is CaseRunStatus.COMPLETED
    assert detail.evaluation_state is EvaluationOutcome.PASS
    _assert_driver_evidence_is_correlated(detail)
    calls = [
        (
            event.payload["tool_name"],
            event.payload["arguments"],
        )
        for event in detail.events
        if event.event_type is RunEventType.TOOL_CALL
    ]
    assert calls == [
        ("get_project_list", {}),
        ("open_project", {"project_id": 430409687}),
    ]
    results = [
        (event.payload["tool_name"], event.payload["source"])
        for event in detail.events
        if event.event_type is RunEventType.TOOL_RESULT
    ]
    assert results == [
        ("get_project_list", "fixture"),
        ("open_project", "fixture"),
    ]
