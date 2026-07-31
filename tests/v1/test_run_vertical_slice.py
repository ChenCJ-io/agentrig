"""create case → async run_cases → Driver → Fixture → Rule → query 的纵切。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome, EvaluatorType
from agentrig.evaluations.schemas import ExternalVerdictSubmit
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.runs.models import CaseRunStatus, RunEventType, RunStatus
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


class ScriptedDriver:
    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self._gate = gate

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(id=f"session-{context.case_run_id}")

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        if self._gate is not None:
            await self._gate.wait()
        yield DriverEvent(
            type=DriverEventType.SESSION_STARTED,
            session_id=session.id,
        )
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[
                ToolCall(
                    id=f"call-{message}",
                    name="search",
                    arguments={"query": message},
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
        assert results[0].source == "fixture"
        yield DriverEvent(type=DriverEventType.ASSISTANT_TEXT_DELTA, text="search complete")
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        session.state["cancelled"] = True

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True


class EvidenceDriver(ScriptedDriver):
    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        yield DriverEvent(
            type=DriverEventType.REQUEST_STARTED,
            request_id="request-user",
            request_kind="chat",
        )
        yield DriverEvent(
            type=DriverEventType.SESSION_STARTED,
            session_id=session.id,
            request_id="request-user",
        )
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_TEXT_DELTA,
            request_id="request-user",
            text="I will check. ",
        )
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            request_id="request-user",
            tool_calls=[
                ToolCall(
                    id=f"call-{message}",
                    name="search",
                    arguments={"query": message},
                )
            ],
        )
        yield DriverEvent(
            type=DriverEventType.REQUEST_COMPLETED,
            request_id="request-user",
            request_kind="chat",
            request_status="completed",
            duration_ms=12.5,
            ttft_ms=4.5,
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session
        assert results[0].source == "fixture"
        yield DriverEvent(
            type=DriverEventType.REQUEST_STARTED,
            request_id="request-tool-result",
            request_kind="tool_result",
        )
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_TEXT_DELTA,
            request_id="request-tool-result",
            text="Search complete.",
        )
        yield DriverEvent(
            type=DriverEventType.REQUEST_COMPLETED,
            request_id="request-tool-result",
            request_kind="tool_result",
            request_status="completed",
            duration_ms=8.0,
            ttft_ms=3.0,
        )


@pytest.fixture
async def container() -> AsyncIterator[ServiceContainer]:
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("scripted", ScriptedDriver)
    services = ServiceContainer.build(
        Settings(),
        database=database,
        drivers=registry,
    )
    await services.initialize()
    yield services
    await services.close()


async def seed_case(
    container: ServiceContainer,
    case_id: str,
    *,
    versions: list[str] | None = None,
) -> None:
    await container.cases.create(
        TestCaseCreate(
            id=case_id,
            name=case_id,
            supported_versions=versions or ["v1"],
            primary_evaluator="rule",
            turns=[
                {
                    "position": 1,
                    "user_message": case_id,
                    "fixtures": [
                        {
                            "tool_name": "search",
                            "match_arguments": {"query": case_id},
                            "result": {"items": [{"id": case_id}]},
                        }
                    ],
                    "assertions": [
                        {"kind": "tool_called", "tool_name": "search"},
                        {"kind": "text_contains", "value": "complete"},
                        {"kind": "no_execution_error"},
                    ],
                }
            ],
        )
    )


async def seed_target_and_profile(container: ServiceContainer) -> None:
    await container.targets.create(
        TargetCreate(
            id="target_scripted",
            name="Scripted Agent",
            driver_type="scripted",
            versions=[{"version": "v1"}, {"version": "v2"}],
        )
    )
    await container.profiles.create(
        ProfileCreate(
            id="profile_fixture",
            name="Fixture only",
            config={
                "tool_mode": "controlled",
                "provider_chain": [{"name": "fixture"}],
                "primary_evaluator": "rule",
                "concurrency": 2,
            },
        )
    )


async def test_async_run_persists_events_and_rule_evaluation(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_search")
    await seed_target_and_profile(container)

    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_search"],
            targets=[{"target_id": "target_scripted", "version": "v1"}],
            profile_id="profile_fixture",
        )
    )
    assert submitted.status is RunStatus.QUEUED
    assert submitted.planned_case_runs == 1
    await container.scheduler.wait(submitted.run_id)

    run = await container.runs.get_run(submitted.run_id)
    assert run.status is RunStatus.COMPLETED
    assert run.completed_count == 1
    page = await container.runs.list_case_runs(run.id)
    assert page.items[0].status is CaseRunStatus.COMPLETED
    assert page.items[0].evaluation_state is EvaluationOutcome.PASS

    detail = await container.runs.get_case_run(page.items[0].id)
    event_types = [event.event_type for event in detail.events]
    assert event_types == [
        RunEventType.USER_MESSAGE,
        RunEventType.DRIVER_SESSION,
        RunEventType.TOOL_CALL,
        RunEventType.PROVIDER_ATTEMPT,
        RunEventType.VALIDATION,
        RunEventType.TOOL_RESULT,
        RunEventType.ASSISTANT_TEXT,
        RunEventType.ASSISTANT_MESSAGE,
    ]
    tool_result = next(
        event
        for event in detail.events
        if event.event_type is RunEventType.TOOL_RESULT
    )
    assert tool_result.payload["source"] == "fixture"
    assert len(detail.evaluations) == 1
    assert detail.evaluations[0].evaluator_type is EvaluatorType.RULE
    assert detail.evaluations[0].verdict == "pass"
    filtered = await container.runs.list_case_run_events(
        detail.id,
        event_types=[RunEventType.TOOL_CALL, RunEventType.TOOL_RESULT],
        limit=1,
    )
    assert filtered.total == 2
    assert filtered.limit == 1
    assert [item.event_type for item in filtered.items] == [
        RunEventType.TOOL_CALL
    ]
    second = await container.runs.list_case_run_events(
        detail.id,
        event_types=[RunEventType.TOOL_CALL, RunEventType.TOOL_RESULT],
        limit=1,
        offset=1,
    )
    assert [item.event_type for item in second.items] == [
        RunEventType.TOOL_RESULT
    ]


async def test_driver_request_session_and_text_order_are_persisted_as_evidence() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("evidence", EvidenceDriver)
    services = ServiceContainer.build(
        Settings(),
        database=database,
        drivers=registry,
    )
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate(
                id="case_evidence_order",
                name="Evidence order",
                supported_versions=["v1"],
                primary_evaluator="rule",
                turns=[
                    {
                        "position": 1,
                        "user_message": "case_evidence_order",
                        "fixtures": [
                            {
                                "tool_name": "search",
                                "match_arguments": {
                                    "query": "case_evidence_order",
                                },
                                "result": {"items": []},
                            }
                        ],
                        "assertions": [
                            {
                                "kind": "first_action",
                                "expected_action": "text",
                            },
                            {"kind": "tool_called", "tool_name": "search"},
                            {
                                "kind": "text_contains",
                                "value": "Search complete",
                            },
                        ],
                    }
                ],
            )
        )
        await services.targets.create(
            TargetCreate(
                id="target_evidence",
                name="Evidence",
                driver_type="evidence",
                options={"nested": {"base": 1, "changed": "base"}},
                versions=[
                    {
                        "version": "v1",
                        "options": {"nested": {"changed": "version"}},
                    }
                ],
            )
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_evidence",
                name="Evidence",
                config={
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_evidence_order"],
                targets=[{"target_id": "target_evidence", "version": "v1"}],
                profile_id="profile_evidence",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(page.items[0].id)

        assert detail.target_snapshot["options"]["nested"] == {
            "base": 1,
            "changed": "version",
        }
        event_types = [event.event_type for event in detail.events]
        assert event_types == [
            RunEventType.USER_MESSAGE,
            RunEventType.DRIVER_REQUEST,
            RunEventType.DRIVER_SESSION,
            RunEventType.ASSISTANT_TEXT,
            RunEventType.TOOL_CALL,
            RunEventType.DRIVER_REQUEST,
            RunEventType.PROVIDER_ATTEMPT,
            RunEventType.VALIDATION,
            RunEventType.TOOL_RESULT,
            RunEventType.DRIVER_REQUEST,
            RunEventType.ASSISTANT_TEXT,
            RunEventType.DRIVER_REQUEST,
            RunEventType.ASSISTANT_MESSAGE,
        ]
        first_text = next(
            event
            for event in detail.events
            if event.event_type is RunEventType.ASSISTANT_TEXT
        )
        tool_call = next(
            event
            for event in detail.events
            if event.event_type is RunEventType.TOOL_CALL
        )
        completed_requests = [
            event
            for event in detail.events
            if event.event_type is RunEventType.DRIVER_REQUEST
            and event.payload["phase"] == "completed"
        ]
        assert first_text.seq < tool_call.seq
        assert tool_call.payload["request_id"] == "request-user"
        assert completed_requests[0].payload["duration_ms"] == 12.5
        assert completed_requests[0].payload["ttft_ms"] == 4.5
        assert detail.evaluations[0].verdict == "pass"
    finally:
        await services.close()


async def test_partial_version_incompatibility_returns_skipped_items(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_v1", versions=["v1"])
    await seed_case(container, "case_v2", versions=["v2"])
    await seed_target_and_profile(container)
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_v1", "case_v2"],
            targets=[{"target_id": "target_scripted", "version": "v2"}],
            profile_id="profile_fixture",
        )
    )
    assert submitted.planned_case_runs == 1
    assert len(submitted.skipped_items) == 1
    assert submitted.skipped_items[0].case_id == "case_v1"
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    assert {item.status for item in page.items} == {
        CaseRunStatus.COMPLETED,
        CaseRunStatus.SKIPPED,
    }


async def test_omitted_version_executes_intersection_and_returns_version_differences(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_v1_only", versions=["v1"])
    await seed_target_and_profile(container)

    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_v1_only"],
            targets=[{"target_id": "target_scripted"}],
            profile_id="profile_fixture",
        )
    )

    assert submitted.planned_case_runs == 1
    assert [
        (item.version, item.code)
        for item in submitted.skipped_items
    ] == [("v2", "version_incompatible")]
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    assert {
        (item.version, item.status)
        for item in page.items
    } == {
        ("v1", CaseRunStatus.COMPLETED),
        ("v2", CaseRunStatus.SKIPPED),
    }
    run = await container.runs.get_run(submitted.run_id)
    assert run.completed_count == 1
    assert run.skipped_count == 1


async def test_case_version_without_target_override_uses_base_and_extra_is_skipped(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_v1_and_v3", versions=["v1", "v3"])
    await seed_target_and_profile(container)

    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_v1_and_v3"],
            targets=[{"target_id": "target_scripted"}],
            profile_id="profile_fixture",
        )
    )

    assert submitted.planned_case_runs == 2
    assert {
        (item.version, item.message)
        for item in submitted.skipped_items
    } == {
        (
            "v2",
            "case case_v1_and_v3 does not support version v2",
        ),
    }
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    assert {
        (item.version, item.status)
        for item in page.items
    } == {
        ("v1", CaseRunStatus.COMPLETED),
        ("v2", CaseRunStatus.SKIPPED),
        ("v3", CaseRunStatus.COMPLETED),
    }


async def test_ab_targets_share_pair_id_per_case_and_repeat(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_ab", versions=["v1", "v2"])
    await seed_target_and_profile(container)
    await container.targets.create(
        TargetCreate(
            id="target_baseline",
            name="Baseline",
            driver_type="scripted",
            versions=[{"version": "v1"}],
        )
    )
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_ab"],
            targets=[
                {
                    "role": "baseline",
                    "target_id": "target_baseline",
                    "version": "v1",
                },
                {
                    "role": "candidate",
                    "target_id": "target_scripted",
                    "version": "v2",
                },
            ],
            profile_id="profile_fixture",
            repeat_count=2,
        )
    )
    assert submitted.planned_case_runs == 4
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    grouped: dict[str, set[str | None]] = {}
    repeats: dict[str, set[int]] = {}
    for item in page.items:
        assert item.comparison_pair_id is not None
        grouped.setdefault(item.comparison_pair_id, set()).add(item.comparison_role)
        repeats.setdefault(item.comparison_pair_id, set()).add(item.repeat_index)
    assert len(grouped) == 2
    assert all(roles == {"baseline", "candidate"} for roles in grouped.values())
    assert {next(iter(values)) for values in repeats.values()} == {1, 2}


async def test_run_cases_returns_before_a_blocked_driver_finishes() -> None:
    gate = asyncio.Event()
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("gated", lambda: ScriptedDriver(gate))
    services = ServiceContainer.build(Settings(), database=database, drivers=registry)
    await services.initialize()
    try:
        await seed_case(services, "case_async")
        await services.targets.create(
            TargetCreate(id="target_gated", name="Gated", driver_type="gated")
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_gated",
                name="Gated",
                config={
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_async"],
                targets=[{"target_id": "target_gated"}],
                profile_id="profile_gated",
            )
        )
        assert submitted.status is RunStatus.QUEUED
        assert (await services.runs.get_run(submitted.run_id)).status in {
            RunStatus.QUEUED,
            RunStatus.RUNNING,
        }
        gate.set()
        await services.scheduler.wait(submitted.run_id)
        assert (await services.runs.get_run(submitted.run_id)).status is RunStatus.COMPLETED
    finally:
        await services.close()


async def test_multiturn_reuses_one_driver_session_and_keeps_order(
    container: ServiceContainer,
) -> None:
    await container.cases.create(
        TestCaseCreate(
            id="case_multiturn",
            name="multi",
            primary_evaluator="rule",
            turns=[
                {
                    "position": 1,
                    "user_message": "create",
                    "fixtures": [
                        {
                            "tool_name": "search",
                            "match_arguments": {"query": "create"},
                            "result": {"items": []},
                        }
                    ],
                    "assertions": [{"kind": "tool_called", "tool_name": "search"}],
                },
                {
                    "position": 2,
                    "user_message": "query",
                    "fixtures": [
                        {
                            "tool_name": "search",
                            "match_arguments": {"query": "query"},
                            "result": {"items": []},
                        }
                    ],
                    "assertions": [{"kind": "tool_called", "tool_name": "search"}],
                },
            ],
        )
    )
    await seed_target_and_profile(container)
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_multiturn"],
            targets=[{"target_id": "target_scripted", "version": "v1"}],
            profile_id="profile_fixture",
        )
    )
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    detail = await container.runs.get_case_run(page.items[0].id)
    user_turns = [
        event.payload["turn_position"]
        for event in detail.events
        if event.event_type is RunEventType.USER_MESSAGE
    ]
    assert user_turns == [1, 2]
    assert detail.summary == {"turn_count": 2, "tool_call_count": 2}
    assert detail.evaluation_state is EvaluationOutcome.PASS


async def test_cancel_is_cooperative_and_preserves_terminal_state() -> None:
    gate = asyncio.Event()
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("gated", lambda: ScriptedDriver(gate))
    services = ServiceContainer.build(Settings(), database=database, drivers=registry)
    await services.initialize()
    try:
        await seed_case(services, "case_cancel")
        await services.targets.create(
            TargetCreate(id="target_cancel", name="Cancel", driver_type="gated")
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_cancel",
                name="Cancel",
                config={
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_cancel"],
                targets=[{"target_id": "target_cancel"}],
                profile_id="profile_cancel",
            )
        )
        await asyncio.sleep(0.01)
        await services.runs.cancel_run(submitted.run_id)
        gate.set()
        await services.scheduler.wait(submitted.run_id)
        assert (await services.runs.get_run(submitted.run_id)).status is RunStatus.CANCELLED
        page = await services.runs.list_case_runs(submitted.run_id)
        assert page.items[0].status is CaseRunStatus.CANCELLED
    finally:
        await services.close()


async def test_case_timeout_fails_item_but_parent_batch_completes() -> None:
    gate = asyncio.Event()
    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("never", lambda: ScriptedDriver(gate))
    services = ServiceContainer.build(Settings(), database=database, drivers=registry)
    await services.initialize()
    try:
        await seed_case(services, "case_timeout")
        await services.targets.create(
            TargetCreate(id="target_timeout", name="Timeout", driver_type="never")
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_timeout",
                name="Timeout",
                config={
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                    "case_timeout_seconds": 0.02,
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_timeout"],
                targets=[{"target_id": "target_timeout"}],
                profile_id="profile_timeout",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        run = await services.runs.get_run(submitted.run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.failed_count == 1
        page = await services.runs.list_case_runs(submitted.run_id)
        assert page.items[0].status is CaseRunStatus.FAILED
        assert (
            page.items[0].evaluation_state
            is EvaluationOutcome.EVALUATION_ERROR
        )
        assert page.items[0].error_code == "case_timeout"
    finally:
        await services.close()


async def test_driver_factory_failure_is_isolated_to_case_run() -> None:
    calls = 0

    def factory() -> ScriptedDriver:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("driver failed while opening")
        return ScriptedDriver()

    database = Database("sqlite+aiosqlite:///:memory:")
    registry = DriverRegistry()
    registry.register("unstable_factory", factory)
    services = ServiceContainer.build(
        Settings(),
        database=database,
        drivers=registry,
    )
    await services.initialize()
    try:
        await seed_case(services, "case_driver_factory")
        await services.targets.create(
            TargetCreate(
                id="target_driver_factory",
                name="Unstable factory",
                driver_type="unstable_factory",
            )
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_driver_factory",
                name="Factory failure",
                config={
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_driver_factory"],
                targets=[{"target_id": "target_driver_factory"}],
                profile_id="profile_driver_factory",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        run = await services.runs.get_run(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.failed_count == 1
        assert page.items[0].status is CaseRunStatus.FAILED
        assert page.items[0].error_code == "internal_error"
        assert page.items[0].error_message == "driver failed while opening"
    finally:
        await services.close()


async def test_external_verdict_is_separate_and_overwrites_only_external_record(
    container: ServiceContainer,
) -> None:
    await seed_case(container, "case_external")
    await seed_target_and_profile(container)
    submitted = await container.runs.run_cases(
        RunCasesRequest(
            case_ids=["case_external"],
            targets=[{"target_id": "target_scripted", "version": "v1"}],
            profile_id="profile_fixture",
        )
    )
    await container.scheduler.wait(submitted.run_id)
    page = await container.runs.list_case_runs(submitted.run_id)
    case_run_id = page.items[0].id
    detail = await container.runs.get_case_run(case_run_id)
    evidence_ref = next(
        event.id
        for event in detail.events
        if event.event_type is RunEventType.ASSISTANT_MESSAGE
    )
    first = await container.runs.submit_external_verdict(
        case_run_id,
        ExternalVerdictSubmit(
            verdict="fail",
            summary="controller found a semantic issue",
            evidence_refs=[evidence_ref],
            submitted_by="codex",
        ),
    )
    second = await container.runs.submit_external_verdict(
        case_run_id,
        ExternalVerdictSubmit(
            verdict="pass",
            summary="controller corrected the verdict",
            evidence_refs=[evidence_ref],
            submitted_by="codex",
        ),
    )
    assert first.id == second.id
    updated = await container.runs.get_case_run(case_run_id)
    assert updated.evaluation_state is EvaluationOutcome.PASS
    assert {item.evaluator_type for item in updated.evaluations} == {
        EvaluatorType.RULE,
        EvaluatorType.EXTERNAL_CONTROLLER,
    }
    rule = next(
        item for item in updated.evaluations if item.evaluator_type is EvaluatorType.RULE
    )
    external = next(
        item
        for item in updated.evaluations
        if item.evaluator_type is EvaluatorType.EXTERNAL_CONTROLLER
    )
    assert rule.verdict == "pass"
    assert external.summary == "controller corrected the verdict"
