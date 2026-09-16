"""Protocol and AgentRig vertical-slice tests for the public reference target."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from examples.reference_target.agentrig_assets import (
    POLICY_CASE_ID,
    RECOVERY_FAILURE_CASE_ID,
    RECOVERY_SUCCESS_CASE_ID,
    REFERENCE_PROFILE_ID,
    REFERENCE_TARGET_ID,
    SUCCESS_CASE_ID,
    canonical_cases,
    reference_profile,
    reference_target,
)
from examples.reference_target.app import create_app

from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.evaluations.models import EvaluationOutcome
from agentrig.infrastructure.database import Database
from agentrig.runs.models import CaseRunStatus, RunEventType, RunStatus
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets.drivers import (
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    HttpSseDriver,
)

TEST_DRIVER_TYPE = "reference_http_sse"


@pytest.fixture
async def reference_services() -> AsyncIterator[ServiceContainer]:
    application = create_app()
    registry = DriverRegistry()
    registry.register(
        TEST_DRIVER_TYPE,
        lambda: HttpSseDriver(transport=httpx.ASGITransport(app=application)),
    )
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
    )
    await services.initialize()
    await services.targets.create(
        reference_target(
            endpoint="http://127.0.0.1:8091",
            driver_type=TEST_DRIVER_TYPE,
        )
    )
    await services.profiles.create(reference_profile())
    for case in canonical_cases():
        await services.cases.create(case)
    yield services
    await services.close()


async def test_reference_target_exposes_health_and_real_sse_protocol() -> None:
    application = create_app()
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://reference.test",
    ) as client:
        health = await client.get("/healthz")
        response = await client.post(
            "/chat/stream",
            json={
                "type": "chat",
                "message": "run",
                "version": "baseline",
                "initial_state": {"reference": {"scenario": "reference_success"}},
            },
        )

    assert health.json() == {
        "status": "ok",
        "deterministic": True,
        "active_sessions": 0,
    }
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type":"request_started"' in response.text
    assert '"type":"session_created"' in response.text
    assert '"name":"reference_lookup"' in response.text
    assert "reference-session-000001:chat:request-01" in response.text


async def test_success_scenario_passes_and_persists_fixture_evidence(
    reference_services: ServiceContainer,
) -> None:
    submitted = await reference_services.runs.run_cases(
        RunCasesRequest(
            case_ids=[SUCCESS_CASE_ID],
            targets=[
                {
                    "target_id": REFERENCE_TARGET_ID,
                    "version": "baseline",
                }
            ],
            profile_id=REFERENCE_PROFILE_ID,
        )
    )
    await reference_services.scheduler.wait(submitted.run_id)

    run = await reference_services.runs.get_run(submitted.run_id)
    page = await reference_services.runs.list_case_runs(submitted.run_id)
    detail = await reference_services.runs.get_case_run(page.items[0].id)

    assert run.status is RunStatus.COMPLETED
    assert page.items[0].status is CaseRunStatus.COMPLETED
    assert page.items[0].evaluation_state is EvaluationOutcome.PASS
    assert any(
        event.event_type is RunEventType.TOOL_RESULT and event.payload["source"] == "fixture"
        for event in detail.events
    )
    assert any(
        event.event_type is RunEventType.ASSISTANT_MESSAGE
        and "Reference lookup completed successfully" in event.payload["text"]
        for event in detail.events
    )


async def test_policy_scenario_produces_stable_baseline_candidate_delta(
    reference_services: ServiceContainer,
) -> None:
    submitted = await reference_services.runs.run_cases(
        RunCasesRequest(
            case_ids=[POLICY_CASE_ID],
            targets=[
                {
                    "role": "baseline",
                    "target_id": REFERENCE_TARGET_ID,
                    "version": "baseline",
                },
                {
                    "role": "candidate",
                    "target_id": REFERENCE_TARGET_ID,
                    "version": "candidate-regression",
                },
            ],
            profile_id=REFERENCE_PROFILE_ID,
        )
    )
    await reference_services.scheduler.wait(submitted.run_id)

    page = await reference_services.runs.list_case_runs(submitted.run_id)
    by_role = {item.comparison_role: item for item in page.items}
    baseline = by_role["baseline"]
    candidate = by_role["candidate"]

    assert baseline.comparison_pair_id == candidate.comparison_pair_id
    assert baseline.comparison_pair_id is not None
    assert baseline.evaluation_state is EvaluationOutcome.PASS
    assert candidate.evaluation_state is EvaluationOutcome.FAIL

    baseline_detail = await reference_services.runs.get_case_run(baseline.id)
    candidate_detail = await reference_services.runs.get_case_run(candidate.id)
    baseline_calls = [
        event for event in baseline_detail.events if event.event_type is RunEventType.TOOL_CALL
    ]
    candidate_calls = [
        event for event in candidate_detail.events if event.event_type is RunEventType.TOOL_CALL
    ]
    assert baseline_calls[0].payload["turn_position"] == 2
    assert candidate_calls[0].payload["turn_position"] == 1


async def test_recovery_uses_new_run_and_preserves_first_failure(
    reference_services: ServiceContainer,
) -> None:
    failed_attempt = await reference_services.runs.run_cases(
        RunCasesRequest(
            case_ids=[RECOVERY_FAILURE_CASE_ID],
            targets=[
                {
                    "target_id": REFERENCE_TARGET_ID,
                    "version": "baseline",
                }
            ],
            profile_id=REFERENCE_PROFILE_ID,
        )
    )
    await reference_services.scheduler.wait(failed_attempt.run_id)
    first_page = await reference_services.runs.list_case_runs(failed_attempt.run_id)
    first_before = first_page.items[0]

    recovered_attempt = await reference_services.runs.run_cases(
        RunCasesRequest(
            case_ids=[RECOVERY_SUCCESS_CASE_ID],
            targets=[
                {
                    "target_id": REFERENCE_TARGET_ID,
                    "version": "baseline",
                }
            ],
            profile_id=REFERENCE_PROFILE_ID,
        )
    )
    await reference_services.scheduler.wait(recovered_attempt.run_id)
    recovered_page = await reference_services.runs.list_case_runs(recovered_attempt.run_id)
    first_after = (await reference_services.runs.list_case_runs(failed_attempt.run_id)).items[0]

    assert failed_attempt.run_id != recovered_attempt.run_id
    assert first_before.status is CaseRunStatus.FAILED
    assert first_before.evaluation_state is EvaluationOutcome.EVALUATION_ERROR
    assert first_before.error_code == "target_unreachable"
    assert first_after == first_before
    assert recovered_page.items[0].status is CaseRunStatus.COMPLETED
    assert recovered_page.items[0].evaluation_state is EvaluationOutcome.PASS


async def test_recovery_attempt_one_is_a_driver_error_not_an_exception() -> None:
    application = create_app()
    driver = HttpSseDriver(transport=httpx.ASGITransport(app=application))
    session = await driver.prepare(
        DriverPrepareContext(
            case_run_id="direct-protocol-check",
            target={"endpoint": "http://reference.test"},
            version="baseline",
            initial_state={"reference": {"scenario": "reference_recovery", "attempt": 1}},
            component_timeout_seconds=5,
        )
    )
    events = [event async for event in driver.send_user_message(session, "run")]
    assert [event.type for event in events] == [DriverEventType.ERROR]
    assert events[0].error == "target HTTP request failed with status 503"
