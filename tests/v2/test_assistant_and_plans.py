"""Assistant 事件、EvaluationPlan 与提交状态机。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from agentrig.agents.invocation_models import AgentRole
from agentrig.agents.invocation_schemas import AgentInvocationCreate
from agentrig.agents.ports import AgentTaskContext
from agentrig.assistant import (
    AssistantMessageCreate,
    AssistantSessionCreate,
    DecisionActionType,
    DecisionKind,
    DecisionStatus,
    DecisionTrigger,
    EvaluationPlanCreate,
    ManagerDecisionProposal,
)
from agentrig.assistant.schemas import (
    EvaluationPlanConfirm,
    EvaluationPlanPatch,
    EvaluationPlanSubmit,
)
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.targets import TargetCreate, TargetPatch
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


class V2Driver:
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
        del session
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[ToolCall(id="call_v2", name="search", arguments={"q": message})],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session, results
        yield DriverEvent(type=DriverEventType.ASSISTANT_TEXT_DELTA, text="done")
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


@pytest.fixture
async def services() -> AsyncIterator[ServiceContainer]:
    registry = DriverRegistry()
    registry.register("v2_test", V2Driver)
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
    )
    await container.initialize()
    await container.cases.create(
        TestCaseCreate(
            id="case_v2_plan",
            name="V2 plan",
            supported_versions=["v1"],
            primary_evaluator="rule",
            turns=[
                {
                    "position": 1,
                    "user_message": "search",
                    "fixtures": [
                        {
                            "tool_name": "search",
                            "match_arguments": {"q": "search"},
                            "result": {"items": []},
                        }
                    ],
                    "assertions": [{"kind": "tool_called", "tool_name": "search"}],
                }
            ],
        )
    )
    await container.targets.create(
        TargetCreate(
            id="target_v2_plan",
            name="V2 target",
            driver_type="v2_test",
            versions=[{"version": "v1"}],
        )
    )
    await container.profiles.create(
        ProfileCreate(
            id="profile_v2_plan",
            name="V2 profile",
            config={
                "provider_chain": [{"name": "fixture"}],
                "primary_evaluator": "rule",
            },
        )
    )
    yield container
    await container.close()


async def _message(services: ServiceContainer) -> tuple[str, str, str]:
    session = await services.assistant.create_session(
        AssistantSessionCreate(title="evaluate search"),
        created_by="user-1",
    )
    first = await services.assistant.send_message(
        session.id,
        AssistantMessageCreate(
            client_message_id="message-1",
            content="evaluate search",
        ),
        actor_id="user-1",
    )
    duplicate = await services.assistant.send_message(
        session.id,
        AssistantMessageCreate(
            client_message_id="message-1",
            content="evaluate search",
        ),
        actor_id="user-1",
    )
    assert duplicate == first
    return session.id, first.event_id, first.turn_id


async def _plan(
    services: ServiceContainer,
) -> tuple[str, str, str]:
    session_id, event_id, turn_id = await _message(services)
    plan = await services.evaluation_plans.create(
        EvaluationPlanCreate(
            session_id=session_id,
            source_turn_id=turn_id,
            goal={"user_request": "evaluate search"},
            selection={
                "case_ids": ["case_v2_plan"],
                "targets": [{"target_id": "target_v2_plan", "version": "v1"}],
                "profile_id": "profile_v2_plan",
            },
            created_by="agentteams_manager",
        )
    )
    assert plan.preview["planned_case_runs"] == 1
    assert plan.confirmation.required is False
    await services.assistant.cancel_turn(turn_id)
    confirmation = await services.assistant.send_message(
        session_id,
        AssistantMessageCreate(
            client_message_id=f"confirm-{plan.id}",
            content=f"confirm {plan.id} revision {plan.revision}",
            active_plan_id=plan.id,
            plan_action={
                "action_type": "confirm_plan",
                "plan_id": plan.id,
                "revision": plan.revision,
            },
        ),
        actor_id="user-1",
    )
    return plan.id, confirmation.event_id, session_id


async def test_message_is_idempotent_and_events_have_monotonic_seq(
    services: ServiceContainer,
) -> None:
    session_id, _, _ = await _message(services)
    page = await services.assistant.list_events(session_id)
    assert [item.seq for item in page.items] == [1]
    assert page.items[0].payload["content"] == "evaluate search"


async def test_new_message_is_rejected_while_previous_turn_is_open(
    services: ServiceContainer,
) -> None:
    session_id, _, turn_id = await _message(services)
    with pytest.raises(AgentRigError) as conflict:
        await services.assistant.send_message(
            session_id,
            AssistantMessageCreate(
                client_message_id="message-2",
                content="a second request",
            ),
            actor_id="user-1",
        )
    assert conflict.value.detail.code is ErrorCode.ASSISTANT_TURN_CONFLICT
    assert conflict.value.detail.retryable is True

    await services.assistant.cancel_turn(turn_id)
    accepted = await services.assistant.send_message(
        session_id,
        AssistantMessageCreate(
            client_message_id="message-2",
            content="a second request",
        ),
        actor_id="user-1",
    )
    assert accepted.turn_id != turn_id


async def test_plan_source_message_cannot_confirm_its_own_draft(
    services: ServiceContainer,
) -> None:
    session_id, event_id, turn_id = await _message(services)
    plan = await services.evaluation_plans.create(
        EvaluationPlanCreate(
            session_id=session_id,
            source_turn_id=turn_id,
            goal={"user_request": "evaluate search"},
            selection={
                "case_ids": ["case_v2_plan"],
                "targets": [{"target_id": "target_v2_plan", "version": "v1"}],
                "profile_id": "profile_v2_plan",
            },
            created_by="agentteams_manager",
        )
    )

    with pytest.raises(AgentRigError) as confirmation_required:
        await services.evaluation_plans.confirm(
            plan.id,
            EvaluationPlanConfirm(
                confirmation_event_id=event_id,
                confirmed_by="user-1",
            ),
        )
    assert confirmation_required.value.detail.code is ErrorCode.PLAN_CONFIRMATION_REQUIRED


async def test_plan_preview_confirm_submit_and_idempotent_retry(
    services: ServiceContainer,
) -> None:
    plan_id, confirmation_event_id, session_id = await _plan(services)
    confirmed = await services.evaluation_plans.confirm(
        plan_id,
        EvaluationPlanConfirm(
            confirmation_event_id=confirmation_event_id,
            confirmed_by="user-1",
        ),
    )
    assert confirmed.status == "confirmed"
    submitted, run = await services.evaluation_plans.submit(
        plan_id,
        EvaluationPlanSubmit(idempotency_key="submit-1"),
    )
    assert submitted.run_id == run.run_id
    await services.scheduler.wait(run.run_id)
    same, same_run = await services.evaluation_plans.submit(
        plan_id,
        EvaluationPlanSubmit(idempotency_key="submit-1"),
    )
    assert same.run_id == same_run.run_id == run.run_id
    context = await services.assistant.get_context(session_id)
    assert context["active_plan"]["run_id"] == run.run_id
    event_types = {
        item.event_type.value for item in (await services.assistant.list_events(session_id)).items
    }
    assert "run_status" in event_types


async def test_managed_plan_actions_are_bound_to_distinct_user_events(
    services: ServiceContainer,
) -> None:
    plan_id, confirmation_event_id, session_id = await _plan(services)
    plan = await services.evaluation_plans.get(plan_id)
    confirmation_event = await services.assistant.get_event(confirmation_event_id)
    assert confirmation_event.turn_id is not None
    confirm_decision = await services.decisions.record(
        ManagerDecisionProposal(
            session_id=session_id,
            turn_id=confirmation_event.turn_id,
            trigger="user_confirmation",
            decision_kind="submission",
            objective="confirm the exact plan revision",
            observation_summary={"known": ["the user selected confirm"]},
            options=[{"action_type": "confirm_plan", "label": "confirm plan"}],
            selected_action={"action_type": "confirm_plan"},
            rationale_summary={"summary": "the structured action matches the plan"},
            evidence_refs=[{"kind": "evaluation_plan", "resource_id": plan_id}],
            idempotency_key="bound-confirm-action",
        )
    )
    services.evaluation_plans._enforce_managed_mutations = True  # noqa: SLF001
    confirmed = await services.evaluation_plans.confirm(
        plan_id,
        EvaluationPlanConfirm(
            confirmation_event_id=confirmation_event_id,
            confirmed_by="user-1",
            decision_id=confirm_decision.id,
        ),
    )
    assert confirmed.status.value == "confirmed"

    await services.assistant.cancel_turn(confirmation_event.turn_id)
    submit_receipt = await services.assistant.send_message(
        session_id,
        AssistantMessageCreate(
            client_message_id="bound-submit-action",
            content=f"submit {plan_id} revision {plan.revision}",
            active_plan_id=plan_id,
            plan_action={
                "action_type": "submit_plan",
                "plan_id": plan_id,
                "revision": plan.revision,
            },
        ),
        actor_id="user-1",
    )
    submit_decision = await services.decisions.record(
        ManagerDecisionProposal(
            session_id=session_id,
            turn_id=submit_receipt.turn_id,
            trigger="user_confirmation",
            decision_kind="submission",
            objective="submit the exact confirmed plan once",
            observation_summary={"known": ["the user selected submit"]},
            options=[{"action_type": "submit_plan", "label": "submit plan"}],
            selected_action={"action_type": "submit_plan"},
            rationale_summary={"summary": "the structured action matches the plan"},
            evidence_refs=[{"kind": "evaluation_plan", "resource_id": plan_id}],
            idempotency_key="bound-submit-decision",
        )
    )
    await services.decisions.authorize(submit_decision.id, submit_receipt.event_id)
    submitted, run = await services.evaluation_plans.submit(
        plan_id,
        EvaluationPlanSubmit(
            idempotency_key="bound-submit-run",
            decision_id=submit_decision.id,
        ),
    )
    await services.scheduler.wait(run.run_id)
    assert submitted.run_id == run.run_id


async def test_draft_plan_can_be_edited_and_repreviewed(
    services: ServiceContainer,
) -> None:
    plan_id, _, _ = await _plan(services)
    updated = await services.evaluation_plans.update(
        plan_id,
        EvaluationPlanPatch(
            reasoning_summary={"selection_rationale": ["edited by user"]},
        ),
    )
    assert updated.status == "draft"
    assert updated.reasoning_summary["selection_rationale"] == ["edited by user"]
    assert updated.preview["planned_case_runs"] == 1


async def test_confirmed_plan_detects_asset_drift(services: ServiceContainer) -> None:
    plan_id, confirmation_event_id, session_id = await _plan(services)
    await services.evaluation_plans.confirm(
        plan_id,
        EvaluationPlanConfirm(
            confirmation_event_id=confirmation_event_id,
            confirmed_by="user-1",
        ),
    )
    confirmation_event = await services.assistant.get_event(confirmation_event_id)
    submit_decision = await services.decisions.record(
        ManagerDecisionProposal(
            session_id=session_id,
            turn_id=confirmation_event.turn_id,
            trigger="user_confirmation",
            decision_kind="submission",
            objective="submit the confirmed plan without changing its frozen scope",
            observation_summary={
                "known": ["the plan has been confirmed"],
                "constraints": ["reject submission when selected assets drift"],
            },
            options=[
                {
                    "action_type": "submit_plan",
                    "label": "submit the confirmed plan",
                }
            ],
            selected_action={"action_type": "submit_plan"},
            rationale_summary={
                "summary": "submit only if the current selection hash remains valid"
            },
            evidence_refs=[
                {
                    "kind": "evaluation_plan",
                    "resource_id": plan_id,
                    "label": "confirmed plan",
                }
            ],
            idempotency_key="submit-stale-decision",
        )
    )
    await services.decisions.authorize(submit_decision.id, confirmation_event_id)
    target = await services.targets.get("target_v2_plan")
    await services.targets.update(
        target.id,
        TargetPatch(name="changed after confirmation"),
    )
    with pytest.raises(AgentRigError) as exc:
        await services.evaluation_plans.submit(
            plan_id,
            EvaluationPlanSubmit(
                idempotency_key="submit-stale",
                decision_id=submit_decision.id,
            ),
        )
    assert exc.value.detail.code is ErrorCode.PLAN_STALE
    failed = await services.decisions.get(submit_decision.id)
    assert failed.status is DecisionStatus.FAILED
    assert failed.error_code == ErrorCode.PLAN_STALE.value


async def test_decision_is_idempotent_and_links_plan_provenance(
    services: ServiceContainer,
) -> None:
    session_id, event_id, turn_id = await _message(services)
    proposal = ManagerDecisionProposal(
        session_id=session_id,
        turn_id=turn_id,
        trigger=DecisionTrigger.USER_REQUEST,
        decision_kind=DecisionKind.EXECUTION_STRATEGY,
        objective="evaluate the approved search case",
        observation_summary={
            "known": ["one approved case and reachable target are available"],
            "constraints": ["use deterministic fixture evidence first"],
        },
        options=[
            {
                "action_type": DecisionActionType.CREATE_PLAN,
                "label": "create a bounded plan",
                "expected_effect": "run one deterministic case",
            }
        ],
        selected_action={
            "action_type": DecisionActionType.CREATE_PLAN,
            "parameters": {"provider_chain": ["fixture"]},
        },
        rationale_summary={
            "summary": "The exact approved case already has deterministic evidence."
        },
        evidence_refs=[{"kind": "assistant_event", "resource_id": event_id}],
        idempotency_key="decision-create-plan-1",
    )
    decision = await services.decisions.record(proposal)
    duplicate = await services.decisions.record(proposal)
    assert duplicate.id == decision.id
    assert decision.status is DecisionStatus.AUTHORIZED

    other_session_id, other_event_id, other_turn_id = await _message(services)
    cross_session_proposal = ManagerDecisionProposal.model_validate(
        {
            **proposal.model_dump(mode="json"),
            "session_id": other_session_id,
            "turn_id": other_turn_id,
            "evidence_refs": [{"kind": "assistant_event", "resource_id": other_event_id}],
        }
    )
    with pytest.raises(AgentRigError) as conflict:
        await services.decisions.record(cross_session_proposal)
    assert conflict.value.detail.code is ErrorCode.DECISION_INVALID

    plan = await services.evaluation_plans.create(
        EvaluationPlanCreate(
            session_id=session_id,
            source_turn_id=turn_id,
            origin_decision_id=decision.id,
            goal={"user_request": "evaluate search"},
            selection={
                "case_ids": ["case_v2_plan"],
                "targets": [{"target_id": "target_v2_plan", "version": "v1"}],
                "profile_id": "profile_v2_plan",
            },
            created_by="agentteams_manager",
        )
    )
    completed = await services.decisions.get(decision.id)
    assert completed.status is DecisionStatus.SUCCEEDED
    assert completed.action_ref_type == "evaluation_plan"
    assert completed.action_ref_id == plan.id
    assert plan.origin_decision_id == decision.id
    decision_events = [
        event
        for event in (await services.assistant.list_events(session_id)).items
        if event.decision_id == decision.id
    ]
    assert {item.event_type.value for item in decision_events} == {
        "decision_recorded",
        "decision_status_changed",
        "plan_created",
    }

    await services.assistant.cancel_turn(turn_id)
    confirmation = await services.assistant.send_message(
        session_id,
        AssistantMessageCreate(
            client_message_id="decision-plan-confirm",
            content=f"confirm {plan.id} revision {plan.revision}",
            active_plan_id=plan.id,
            plan_action={
                "action_type": "confirm_plan",
                "plan_id": plan.id,
                "revision": plan.revision,
            },
        ),
        actor_id="user-1",
    )
    await services.evaluation_plans.confirm(
        plan.id,
        EvaluationPlanConfirm(
            confirmation_event_id=confirmation.event_id,
            confirmed_by="user-1",
        ),
    )
    submit_decision = await services.decisions.record(
        ManagerDecisionProposal(
            session_id=session_id,
            turn_id=turn_id,
            parent_decision_id=decision.id,
            trigger="user_confirmation",
            decision_kind="submission",
            objective="submit the exact confirmed plan once",
            observation_summary={"known": ["the plan is confirmed and unchanged"]},
            options=[{"action_type": "submit_plan", "label": "submit one run"}],
            selected_action={"action_type": "submit_plan", "parameters": {"plan_id": plan.id}},
            rationale_summary={"summary": "The bounded plan is ready."},
            evidence_refs=[
                {"kind": "assistant_event", "resource_id": event_id},
                {"kind": "evaluation_plan", "resource_id": plan.id},
            ],
            idempotency_key="decision-submit-plan-1",
        )
    )
    await services.decisions.authorize(submit_decision.id, event_id)
    submitted, run = await services.evaluation_plans.submit(
        plan.id,
        EvaluationPlanSubmit(
            idempotency_key="decision-linked-submit",
            decision_id=submit_decision.id,
        ),
    )
    await services.scheduler.wait(run.run_id)
    assert submitted.run_id == run.run_id
    run_decisions = await services.decisions.list_for_run(run.run_id)
    assert {item.id for item in run_decisions.items} == {
        decision.id,
        submit_decision.id,
    }


async def test_decision_confirmation_requires_same_session_user_event(
    services: ServiceContainer,
) -> None:
    session_id, event_id, turn_id = await _message(services)
    proposal = ManagerDecisionProposal(
        session_id=session_id,
        turn_id=turn_id,
        trigger="user_confirmation",
        decision_kind="submission",
        objective="submit the confirmed evaluation plan",
        observation_summary={"known": ["the user requested execution"]},
        options=[{"action_type": "submit_plan", "label": "submit one run"}],
        selected_action={"action_type": "submit_plan"},
        rationale_summary={"summary": "The exact scope is ready for submission."},
        evidence_refs=[{"kind": "assistant_event", "resource_id": event_id}],
    )
    decision = await services.decisions.record(proposal)
    assert decision.status is DecisionStatus.AWAITING_CONFIRMATION
    authorized = await services.decisions.authorize(decision.id, event_id)
    assert authorized.status is DecisionStatus.AUTHORIZED

    other = await services.assistant.create_session(
        AssistantSessionCreate(title="other"),
        created_by="user-2",
    )
    other_message = await services.assistant.send_message(
        other.id,
        AssistantMessageCreate(client_message_id="other-1", content="confirm"),
        actor_id="user-2",
    )
    second = await services.decisions.record(
        proposal.model_copy(update={"idempotency_key": "second-submission"})
    )
    with pytest.raises(AgentRigError) as exc:
        await services.decisions.authorize(second.id, other_message.event_id)
    assert exc.value.detail.code is ErrorCode.DECISION_CONFIRMATION_REQUIRED


async def test_concurrent_decisions_allocate_unique_ordinals_and_deduplicate_events(
    services: ServiceContainer,
) -> None:
    session_id, event_id, turn_id = await _message(services)

    def proposal(index: int, key: str) -> ManagerDecisionProposal:
        return ManagerDecisionProposal(
            session_id=session_id,
            turn_id=turn_id,
            trigger="user_request",
            decision_kind="clarification",
            objective=f"resolve bounded question {index}",
            observation_summary={"known": ["the request is persisted"]},
            options=[{"action_type": "no_action", "label": "record evidence"}],
            selected_action={"action_type": "no_action"},
            rationale_summary={"summary": "No mutation is needed."},
            evidence_refs=[{"kind": "assistant_event", "resource_id": event_id}],
            idempotency_key=key,
        )

    records = await asyncio.gather(
        services.decisions.record(proposal(1, "concurrent-1")),
        services.decisions.record(proposal(2, "concurrent-2")),
        services.decisions.record(proposal(1, "concurrent-1")),
    )
    assert records[0].id == records[2].id
    assert sorted({item.ordinal for item in records}) == [1, 2]
    decision_events = [
        item
        for item in (await services.assistant.list_events(session_id)).items
        if item.event_type.value == "decision_recorded"
    ]
    assert len(decision_events) == 2
    metrics = await services.decisions.metrics(session_id)
    assert metrics.decision_count == 2
    assert metrics.succeeded_count == 2
    assert metrics.success_rate == 1.0
    assert metrics.evidence_reference_count == 2
    assert metrics.evidence_kind_coverage == ["assistant_event"]
    assert metrics.provenance_link_rate is None


async def test_decision_validates_asset_evidence_and_configured_limits(
    services: ServiceContainer,
) -> None:
    session_id, _, turn_id = await _message(services)
    proposal = ManagerDecisionProposal(
        session_id=session_id,
        turn_id=turn_id,
        trigger="user_request",
        decision_kind="scope_selection",
        objective="select only existing approved evaluation assets",
        observation_summary={"known": ["the requested assets exist"]},
        options=[{"action_type": "create_plan", "label": "create one plan"}],
        selected_action={"action_type": "create_plan"},
        rationale_summary={"summary": "Use the exact persisted assets."},
        evidence_refs=[
            {"kind": "test_case", "resource_id": "case_v2_plan", "version": "draft"},
            {"kind": "target", "resource_id": "target_v2_plan", "version": "v1"},
            {"kind": "execution_profile", "resource_id": "profile_v2_plan"},
            {"kind": "target_check", "resource_id": "target_v2_plan"},
        ],
        idempotency_key="validated-assets",
    )
    decision = await services.decisions.record(proposal)
    assert decision.status is DecisionStatus.AUTHORIZED

    missing = ManagerDecisionProposal.model_validate(
        {
            **proposal.model_dump(mode="json"),
            "idempotency_key": "missing-asset",
            "evidence_refs": [{"kind": "test_case", "resource_id": "case_missing"}],
        }
    )
    with pytest.raises(AgentRigError) as exc:
        await services.decisions.record(missing)
    assert exc.value.detail.code is ErrorCode.DECISION_INVALID

    unknown_version = ManagerDecisionProposal.model_validate(
        {
            **proposal.model_dump(mode="json"),
            "idempotency_key": "unknown-case-version",
            "evidence_refs": [
                {
                    "kind": "test_case",
                    "resource_id": "case_v2_plan",
                    "version": "invented",
                }
            ],
        }
    )
    with pytest.raises(AgentRigError) as version_error:
        await services.decisions.record(unknown_version)
    assert version_error.value.detail.code is ErrorCode.DECISION_INVALID


async def test_recovery_decisions_enforce_configured_worker_budget(
    services: ServiceContainer,
) -> None:
    session_id, _, turn_id = await _message(services)
    invocation = await services.agent_invocations.create_or_get(
        AgentInvocationCreate(
            role=AgentRole.EVIDENCE_JUDGE,
            context=AgentTaskContext(
                run_id="run_recovery_budget",
                case_run_id="case_run_recovery_budget",
                session_id=session_id,
            ),
            input_snapshot={"evidence": []},
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key="recovery-budget-invocation",
        )
    )

    def proposal(key: str) -> ManagerDecisionProposal:
        return ManagerDecisionProposal(
            session_id=session_id,
            turn_id=turn_id,
            trigger="evidence_inconclusive",
            decision_kind="recovery",
            objective="request one bounded correction from the evidence judge",
            observation_summary={"known": ["the first result is inconclusive"]},
            options=[
                {
                    "action_type": "request_worker_correction",
                    "label": "request a corrected result",
                }
            ],
            selected_action={"action_type": "request_worker_correction"},
            rationale_summary={"summary": "One correction attempt is permitted."},
            evidence_refs=[{"kind": "agent_invocation", "resource_id": invocation.id}],
            idempotency_key=key,
        )

    first = await services.decisions.record(proposal("worker-correction-1"))
    assert first.status is DecisionStatus.AUTHORIZED
    duplicate = await services.decisions.record(proposal("worker-correction-1"))
    assert duplicate.id == first.id
    with pytest.raises(AgentRigError) as exhausted:
        await services.decisions.record(proposal("worker-correction-2"))
    assert exhausted.value.detail.code is ErrorCode.DECISION_RETRY_EXHAUSTED


async def test_enforced_managed_plan_requires_decision() -> None:
    container = ServiceContainer.build(
        Settings(
            adaptive_decisions={
                "enabled": True,
                "enforce_managed_mutations": True,
                "max_options": 1,
            }
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await container.initialize()
    try:
        session_id, event_id, turn_id = await _message(container)
        with pytest.raises(AgentRigError) as required:
            await container.evaluation_plans.create(
                EvaluationPlanCreate(
                    session_id=session_id,
                    source_turn_id=turn_id,
                    goal={"user_request": "must be authorized"},
                    selection={
                        "case_ids": ["case_missing"],
                        "targets": [{"target_id": "target_missing"}],
                        "profile_id": "profile_missing",
                    },
                    created_by="agentteams_manager",
                )
            )
        assert required.value.detail.code is ErrorCode.DECISION_REQUIRED

        too_many_options = ManagerDecisionProposal(
            session_id=session_id,
            turn_id=turn_id,
            trigger="user_request",
            decision_kind="clarification",
            objective="respect configured decision limits",
            observation_summary={"known": ["one user request exists"]},
            options=[
                {"action_type": "ask_user", "label": "ask"},
                {"action_type": "no_action", "label": "stop"},
            ],
            selected_action={"action_type": "ask_user"},
            rationale_summary={"summary": "The configured limit is one option."},
            evidence_refs=[{"kind": "assistant_event", "resource_id": event_id}],
        )
        with pytest.raises(AgentRigError) as limited:
            await container.decisions.record(too_many_options)
        assert limited.value.detail.code is ErrorCode.DECISION_INVALID
    finally:
        await container.close()
