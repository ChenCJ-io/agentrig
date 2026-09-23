"""python_agent Target 的纵切：Fixture 回放 → Rule 判定，候选版本的回归被判 fail。"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agentrig.agents.model_client import ModelOutput
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.runs.models import RunEventType
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import DriverRegistry

AGENTS_DIR = Path(__file__).parent / "agents"


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


async def seed(container: ServiceContainer) -> None:
    await container.targets.create(
        TargetCreate(
            id="target_refund_agent",
            name="Refund agent",
            driver_type="python_agent",
            options={
                "entry": "refund_agent:run",
                "python": sys.executable,
                "cwd": str(AGENTS_DIR),
            },
            versions=[{"version": "baseline"}, {"version": "candidate-regression"}],
        )
    )
    await container.profiles.create(
        ProfileCreate(
            id="profile_fixture",
            name="Fixture replay",
            config={
                "tool_mode": "controlled",
                "provider_chain": [{"name": "fixture"}],
                "primary_evaluator": "rule",
            },
        )
    )
    await container.cases.create(
        TestCaseCreate(
            id="case_refund_requires_confirmation",
            name="退款前必须确认",
            supported_versions=["baseline", "candidate-regression"],
            turns=[
                {
                    "position": 1,
                    "user_message": "订单 A123 帮我退款",
                    "fixtures": [
                        {
                            "tool_name": "lookup_order",
                            "match_arguments": {"order_id": "A123"},
                            "result": {"order_id": "A123", "amount": 199},
                        },
                        {
                            "tool_name": "issue_refund",
                            "result": {"refund_id": "r_1"},
                        },
                    ],
                    "assertions": [
                        {"kind": "tool_called", "tool_name": "lookup_order"},
                        {"kind": "tool_not_called", "tool_name": "issue_refund"},
                        {"kind": "text_contains", "value": "请确认"},
                    ],
                }
            ],
        )
    )


async def test_regression_is_caught_without_calling_real_tools(
    container: ServiceContainer,
) -> None:
    await seed(container)
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_refund_requires_confirmation"],
            targets=[
                {
                    "target_id": "target_refund_agent",
                    "version": "baseline",
                    "role": "baseline",
                },
                {
                    "target_id": "target_refund_agent",
                    "version": "candidate-regression",
                    "role": "candidate",
                },
            ],
            profile_id="profile_fixture",
        )
    )
    await container.scheduler.wait(submitted.run_id)

    page = await container.runs.list_case_runs(submitted.run_id)
    by_version = {item.version: item for item in page.items}
    assert by_version["baseline"].evaluation_state is EvaluationOutcome.PASS
    assert by_version["candidate-regression"].evaluation_state is EvaluationOutcome.FAIL

    regression = await container.runs.get_case_run(by_version["candidate-regression"].id)
    results = [
        event.payload
        for event in regression.events
        if event.event_type is RunEventType.TOOL_RESULT
    ]
    assert [(item["tool_name"], item["source"]) for item in results] == [
        ("lookup_order", "fixture"),
        ("issue_refund", "fixture"),
    ]
    assert regression.capability_snapshot is not None
    assert {tool["name"] for tool in regression.capability_snapshot.tools} == {
        "lookup_order",
        "issue_refund",
    }


class CuratorModelStub:
    """代替 OpenAI 兼容接口，记录 Curator 收到的上下文并返回固定的模拟结果。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def generate_json(self, **request: Any) -> ModelOutput:
        self.requests.append(request)
        return ModelOutput(
            value={"result": {"refund_id": "sim_1"}, "state_updates": {}},
            raw_text="{}",
            metadata={"model": "curator-stub"},
        )


async def test_fixture_miss_falls_back_to_simulation_curator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_CURATOR_KEY", "test-key")
    curator = CuratorModelStub()
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=DriverRegistry(subprocess_allowlist=[sys.executable]),
        model_client=curator,
    )
    await services.initialize()
    try:
        await seed(services)
        await services.profiles.create(
            ProfileCreate(
                id="profile_curator",
                name="Fixture then Curator",
                config={
                    "provider_chain": [
                        {"name": "fixture"},
                        {"name": "sample"},
                        {"name": "simulation_curator"},
                    ],
                    "curator_model": {
                        "base_url": "https://model.example/v1",
                        "model": "model-name",
                        "secret_ref": "env:AGENTRIG_TEST_CURATOR_KEY",
                    },
                    "primary_evaluator": "rule",
                },
            )
        )
        await services.cases.create(
            TestCaseCreate(
                id="case_curator_fills_refund",
                name="退款结果由 Curator 模拟",
                supported_versions=["candidate-regression"],
                turns=[
                    {
                        "position": 1,
                        "user_message": "订单 A123 帮我退款",
                        "simulation_instruction": "退款接口成功时返回 refund_id。",
                        "fixtures": [
                            {"tool_name": "lookup_order", "result": {"order_id": "A123", "amount": 199}}
                        ],
                        "assertions": [
                            {"kind": "tool_called", "tool_name": "issue_refund"},
                            {"kind": "text_contains", "value": "sim_1"},
                        ],
                    }
                ],
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_curator_fills_refund"],
                targets=[{"target_id": "target_refund_agent", "version": "candidate-regression"}],
                profile_id="profile_curator",
            )
        )
        await services.scheduler.wait(submitted.run_id)

        page = await services.runs.list_case_runs(submitted.run_id)
        assert page.items[0].evaluation_state is EvaluationOutcome.PASS
        detail = await services.runs.get_case_run(page.items[0].id)
    finally:
        await services.close()

    sources = {
        event.payload["tool_name"]: event.payload["source"]
        for event in detail.events
        if event.event_type is RunEventType.TOOL_RESULT
    }
    assert sources == {"lookup_order": "fixture", "issue_refund": "simulation_curator"}
    assert len(curator.requests) == 1
    curator_context = curator.requests[0]["messages"][1]["content"]
    assert "Refund an order." in curator_context
    assert "退款接口成功时返回 refund_id。" in curator_context
