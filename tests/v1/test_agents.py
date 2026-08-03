"""Simulation Curator 与 Evidence Judge 的结构化输出和修正边界。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest

from agentrig.agents import EvidenceJudge, SimulationCurator
from agentrig.agents.model_client import ModelOutput
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationRecordStatus, EvaluatorType
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.secrets import SecretResolver
from agentrig.profiles import ProfileCreate
from agentrig.profiles.schemas import ModelConfigRef
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.runs.schemas import CaseRunDetail, RunCasesRequest, RunEvent
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)
from agentrig.tool_results.providers import (
    ProviderContext,
    ProviderStatus,
    SimulationCuratorProvider,
)
from agentrig.tool_results.validator import ToolResultValidator


class FakeModelClient:
    def __init__(self, outputs: list[Any]) -> None:
        self.outputs = outputs
        self.requests: list[dict[str, Any]] = []

    async def generate_json(self, **request: Any) -> ModelOutput:
        self.requests.append(request)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return ModelOutput(value=value, raw_text="{}", metadata={"model": "fake"})


class AgentIntegrationDriver:
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(id=context.case_run_id)

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        del session, message
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[
                ToolCall(
                    id="call_curator",
                    name="search",
                    arguments={"q": "hello"},
                    result_schema={
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}},
                    },
                )
            ],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session
        assert results[0].source == "simulation_curator"
        yield DriverEvent(type=DriverEventType.ASSISTANT_TEXT_DELTA, text="grounded")
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


@pytest.fixture
def model_config(monkeypatch: pytest.MonkeyPatch) -> ModelConfigRef:
    monkeypatch.setenv("AGENTRIG_TEST_MODEL_KEY", "secret")
    return ModelConfigRef(
        base_url="http://model.test/v1",
        model="fake",
        secret_ref="env:AGENTRIG_TEST_MODEL_KEY",
    )


async def test_curator_receives_runtime_context_and_corrects_once(
    model_config: ModelConfigRef,
) -> None:
    client = FakeModelClient(
        [
            {"result": {"wrong": True}, "state_updates": {}},
            {"result": {"items": []}, "state_updates": {"last_query": "hello"}},
        ]
    )
    provider = SimulationCuratorProvider(
        SimulationCurator(client, SecretResolver()),
        model_config=model_config,
        timeout_seconds=10,
        validator=ToolResultValidator(),
    )
    context = ProviderContext(
        case_run_id="cr",
        turn_position=2,
        tool_call=ToolCall(
            id="call",
            name="search",
            arguments={"query": "hello"},
            result_schema={
                "type": "object",
                "required": ["items"],
                "properties": {"items": {"type": "array"}},
            },
        ),
        initial_state={"tenant": "demo"},
        simulation_instruction="return no matches",
        prior_events=[{"event_type": "assistant_message", "payload": {"text": "before"}}],
    )
    response = await provider.resolve(context)
    assert response.status is ProviderStatus.HIT
    assert response.result == {"items": []}
    assert len(client.requests) == 2
    assert context.simulation_state == {"last_query": "hello"}
    correction_prompt = client.requests[1]["messages"][1]["content"]
    assert "required property" in correction_prompt
    assert "rubric" not in correction_prompt
    assert "expected" not in correction_prompt


async def test_curator_accepts_valid_unwrapped_json_without_schema_mode(
    model_config: ModelConfigRef,
) -> None:
    client = FakeModelClient([{"items": [], "available": True}])
    provider = SimulationCuratorProvider(
        SimulationCurator(client, SecretResolver()),
        model_config=model_config.model_copy(
            update={"options": {"structured_output": False}}
        ),
        timeout_seconds=10,
        validator=ToolResultValidator(),
    )
    response = await provider.resolve(
        ProviderContext(
            case_run_id="cr",
            turn_position=1,
            tool_call=ToolCall(id="call", name="search"),
        )
    )
    assert response.status is ProviderStatus.HIT
    assert response.result == {"items": [], "available": True}


async def test_curator_model_failure_is_provider_error_without_invalid_injection(
    model_config: ModelConfigRef,
) -> None:
    client = FakeModelClient([RuntimeError("unavailable")])
    provider = SimulationCuratorProvider(
        SimulationCurator(client, SecretResolver()),
        model_config=model_config,
        timeout_seconds=10,
        validator=ToolResultValidator(),
    )
    response = await provider.resolve(
        ProviderContext(
            case_run_id="cr",
            turn_position=1,
            tool_call=ToolCall(id="call", name="search"),
        )
    )
    assert response.status is ProviderStatus.ERROR
    assert "unavailable" in (response.message or "")


def judge_detail() -> CaseRunDetail:
    now = datetime.now(timezone.utc)
    return CaseRunDetail(
        id="cr",
        run_id="run",
        case_id="case",
        case_snapshot={
            "case_rubric": "answer should be grounded",
            "turns": [{"position": 1, "rubric": None}],
        },
        target_snapshot={},
        profile_snapshot={},
        version=None,
        repeat_index=1,
        comparison_pair_id=None,
        comparison_role="candidate",
        status=CaseRunStatus.COMPLETED,
        primary_evaluator=EvaluatorType.EVIDENCE_JUDGE,
        evaluation_state="awaiting_verdict",
        started_at=now,
        finished_at=now,
        error_code=None,
        error_message=None,
        summary={},
        events=[
            RunEvent(
                id="evt_1",
                case_run_id="cr",
                seq=1,
                event_type=RunEventType.ASSISTANT_MESSAGE,
                payload={"text": "grounded"},
                created_at=now,
            )
        ],
        evaluations=[],
    )


async def test_judge_retries_invalid_evidence_ref_then_returns_valid_result(
    model_config: ModelConfigRef,
) -> None:
    client = FakeModelClient(
        [
            {
                "verdict": "pass",
                "summary": "bad ref",
                "criteria": [],
                "evidence_refs": ["evt_missing"],
            },
            {
                "verdict": "pass",
                "summary": "grounded",
                "criteria": [
                    {
                        "criterion": "grounded",
                        "verdict": "pass",
                        "evidence_refs": ["evt_1"],
                    }
                ],
                "evidence_refs": ["evt_1"],
            },
        ]
    )
    result = await EvidenceJudge(client, SecretResolver()).evaluate(
        judge_detail(),
        rule_result=None,
        model_config=model_config,
        timeout_seconds=10,
    )
    assert result.status is EvaluationRecordStatus.COMPLETED
    assert result.verdict == "pass"
    assert result.evidence_refs == ["evt_1"]
    assert result.config_snapshot["attempts"] == 2
    assert "unknown evidence_refs" in client.requests[1]["messages"][1]["content"]


async def test_judge_invalid_twice_is_evaluation_error_not_fail(
    model_config: ModelConfigRef,
) -> None:
    invalid = {
        "verdict": "pass",
        "summary": "bad",
        "criteria": [],
        "evidence_refs": ["unknown"],
    }
    result = await EvidenceJudge(
        FakeModelClient([invalid, invalid]),
        SecretResolver(),
    ).evaluate(
        judge_detail(),
        rule_result=None,
        model_config=model_config,
        timeout_seconds=10,
    )
    assert result.status is EvaluationRecordStatus.ERROR
    assert result.verdict is None
    assert "validation failed" in result.summary


async def test_curator_and_judge_are_integrated_but_have_separate_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_MODEL_KEY", "secret")
    client = FakeModelClient(
        [
            {"result": {"items": [{"id": 1}]}, "state_updates": {"found": 1}},
            {
                "verdict": "pass",
                "summary": "grounded",
                "criteria": [],
                "evidence_refs": [],
            },
        ]
    )
    registry = DriverRegistry()
    registry.register("agent_integration", AgentIntegrationDriver)
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
        model_client=client,
    )
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate(
                id="case_agents",
                name="agents",
                primary_evaluator="evidence_judge",
                case_rubric="SECRET_JUDGE_RUBRIC",
                turns=[
                    {
                        "position": 1,
                        "user_message": "hello",
                        "simulation_instruction": "return one plausible item",
                        "assertions": [{"kind": "tool_called", "tool_name": "search"}],
                    }
                ],
            )
        )
        await services.targets.create(
            TargetCreate(
                id="target_agents",
                name="Agents",
                driver_type="agent_integration",
            )
        )
        model_ref = {
            "base_url": "http://model.test/v1",
            "model": "fake",
            "secret_ref": "env:AGENTRIG_TEST_MODEL_KEY",
        }
        await services.profiles.create(
            ProfileCreate(
                id="profile_agents",
                name="Agents",
                config={
                    "provider_chain": [{"name": "simulation_curator"}],
                    "primary_evaluator": "evidence_judge",
                    "curator_model": model_ref,
                    "judge_model": model_ref,
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_agents"],
                targets=[{"target_id": "target_agents"}],
                profile_id="profile_agents",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(page.items[0].id)
        assert detail.evaluation_state == "pass"
        assert {item.evaluator_type for item in detail.evaluations} == {
            EvaluatorType.RULE,
            EvaluatorType.EVIDENCE_JUDGE,
        }
        tool_result = next(
            event for event in detail.events if event.event_type is RunEventType.TOOL_RESULT
        )
        assert tool_result.payload["source"] == "simulation_curator"
        curator_prompt = client.requests[0]["messages"][1]["content"]
        judge_prompt = client.requests[1]["messages"][1]["content"]
        assert "SECRET_JUDGE_RUBRIC" not in curator_prompt
        assert "SECRET_JUDGE_RUBRIC" in judge_prompt
    finally:
        await services.close()
