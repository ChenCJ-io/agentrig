"""Fixture/Sample 的确定性匹配与 Provider 降级。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import ExecutionConfig, Settings
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.repositories import SqlSampleRepository
from agentrig.profiles import ProfileCreate
from agentrig.profiles.schemas import ProviderSpec
from agentrig.runs.models import RunEventType
from agentrig.runs.schemas import RunCasesRequest
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
from agentrig.tool_results import SampleCreate
from agentrig.tool_results.chain import build_provider_chain
from agentrig.tool_results.models import SampleStatus
from agentrig.tool_results.providers import (
    FixtureProvider,
    ProviderContext,
    ProviderStatus,
    RealToolProvider,
)
from agentrig.tool_results.validator import ToolResultValidator


class FakeRealToolClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool_name, arguments))
        return {"items": [{"id": 1}]}


class RealToolDriver:
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
                    id="real_call",
                    name="tools__search",
                    arguments={"q": "hello"},
                )
            ],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session
        assert results[0].source == "real_tool"
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


async def test_fixture_is_ordered_one_shot_unless_repeatable() -> None:
    provider = FixtureProvider()
    context = ProviderContext(
        case_run_id="cr",
        turn_position=1,
        tool_call=ToolCall(id="call", name="search", arguments={"q": "x", "limit": 10}),
        fixtures=[
            {
                "tool_name": "search",
                "match_arguments": {"q": "x"},
                "result": {"index": 1},
            },
            {
                "tool_name": "search",
                "match_arguments": {"q": "x"},
                "result": {"index": 2},
            },
        ],
    )
    first = await provider.resolve(context)
    second = await provider.resolve(context)
    third = await provider.resolve(context)
    assert first.result == {"index": 1}
    assert second.result == {"index": 2}
    assert third.status is ProviderStatus.MISS


async def test_chain_falls_through_fixture_miss_to_first_approved_sample() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    repository = SqlSampleRepository(database)
    try:
        await repository.create(
            "sample_1",
            SampleCreate(
                name="first",
                tool_name="search",
                content={"items": [1]},
                match_arguments={"query": "hello", "request_id": "old"},
                ignored_argument_paths=["request_id"],
                supported_versions=["v1"],
            ),
            source_type="manual",
        )
        await repository.set_status("sample_1", SampleStatus.APPROVED)
        chain = build_provider_chain(
            [ProviderSpec(name="fixture"), ProviderSpec(name="sample")],
            samples=repository,
            validator=ToolResultValidator(),
        )
        resolution = await chain.resolve(
            ProviderContext(
                case_run_id="cr",
                turn_position=1,
                tool_call=ToolCall(
                    id="call",
                    name="search",
                    arguments={"query": "hello", "request_id": "new"},
                ),
                version="v1",
            )
        )
        assert resolution.result.source == "sample"
        assert resolution.result.result == {"items": [1]}
        assert [item.status for item in resolution.attempts] == [
            ProviderStatus.MISS,
            ProviderStatus.HIT,
        ]
    finally:
        await database.dispose()


async def test_sequence_sample_consumes_steps_in_order_per_chain() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    repository = SqlSampleRepository(database)
    try:
        await repository.create(
            "sample_sequence",
            SampleCreate(
                name="ordered sequence",
                sample_kind="sequence",
                content=[
                    {
                        "tool_name": "create",
                        "match_arguments": {"name": "A"},
                        "result": {"id": "order-1"},
                    },
                    {
                        "tool_name": "query",
                        "match_arguments": {"id": "order-1"},
                        "result": {"status": "created"},
                    },
                ],
                supported_versions=["v1"],
            ),
            source_type="manual",
        )
        await repository.set_status("sample_sequence", SampleStatus.APPROVED)
        chain = build_provider_chain(
            [ProviderSpec(name="sample")],
            samples=repository,
            validator=ToolResultValidator(),
        )
        first = await chain.resolve(
            ProviderContext(
                case_run_id="cr",
                turn_position=1,
                tool_call=ToolCall(
                    id="call_1",
                    name="create",
                    arguments={"name": "A"},
                ),
                version="v1",
            )
        )
        second = await chain.resolve(
            ProviderContext(
                case_run_id="cr",
                turn_position=2,
                tool_call=ToolCall(
                    id="call_2",
                    name="query",
                    arguments={"id": "order-1"},
                ),
                version="v1",
            )
        )
        assert first.result.result == {"id": "order-1"}
        assert first.result.metadata["step_index"] == 0
        assert second.result.result == {"status": "created"}
        assert second.result.metadata["step_index"] == 1
    finally:
        await database.dispose()


async def test_real_tool_requires_allowlist() -> None:
    client = FakeRealToolClient()
    context = ProviderContext(
        case_run_id="cr",
        turn_position=1,
        tool_call=ToolCall(id="call", name="tools__search", arguments={"q": "x"}),
    )
    denied = await RealToolProvider(
        client,
        allowlist=[],
        timeout_seconds=1,
    ).resolve(context)
    allowed = await RealToolProvider(
        client,
        allowlist=["tools:*"],
        timeout_seconds=1,
    ).resolve(context)
    assert denied.status is ProviderStatus.ERROR
    assert allowed.status is ProviderStatus.HIT
    assert len(client.calls) == 1


async def test_real_tool_evidence_requires_explicit_sample_creation() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("real_tool_test", RealToolDriver)
    real_client = FakeRealToolClient()
    services = ServiceContainer.build(
        Settings(execution=ExecutionConfig(real_tool_allowlist=["tools:*"])),
        database=database,
        drivers=registry,
        real_tool_client=real_client,
    )
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate(
                id="case_real",
                name="real",
                primary_evaluator="rule",
                turns=[
                    {
                        "position": 1,
                        "user_message": "search",
                        "assertions": [{"kind": "tool_called", "tool_name": "tools__search"}],
                    }
                ],
            )
        )
        await services.targets.create(
            TargetCreate(
                id="target_real",
                name="real",
                driver_type="real_tool_test",
            )
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_real",
                name="real",
                config={
                    "provider_chain": [{"name": "real_tool"}],
                    "primary_evaluator": "rule",
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_real"],
                targets=[{"target_id": "target_real"}],
                profile_id="profile_real",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(page.items[0].id)
        assert (await services.samples.list_samples()).total == 0
        tool_call_event = next(
            event for event in detail.events if event.event_type is RunEventType.TOOL_CALL
        )
        sample = await services.samples.create(
            SampleCreate(
                name="captured real result",
                source_tool_call_id=tool_call_event.id,
            )
        )
        assert sample.status is SampleStatus.DRAFT
        assert sample.tool_name == "tools__search"
        assert sample.content == {"items": [{"id": 1}]}
    finally:
        await services.close()
