"""单个 CaseRun 的多轮执行闭环。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..agents import EvidenceJudge, SimulationCurator
from ..errors import AgentRigError, ErrorCode
from ..evaluations.models import (
    EvaluationOutcome,
    EvaluationRecordStatus,
    EvaluatorType,
)
from ..evaluations.repository import EvaluationRepository
from ..evaluations.rule_evaluator import RuleEvaluator
from ..evaluations.schemas import EvaluationDraft, EvaluationResult
from ..infrastructure.secrets import SecretResolver
from ..profiles.models import ProviderName, ToolMode
from ..profiles.schemas import ExecutionProfileConfig
from ..proxy.scoped import ProxyScope, ProxyScopeRegistry
from ..targets.drivers import (
    AgentDriver,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)
from ..tool_results.chain import ProviderChain, ProviderExhausted, build_provider_chain
from ..tool_results.providers import (
    ProviderAttempt,
    ProviderContext,
    RealToolClient,
    RealToolProvider,
    SimulationCuratorProvider,
    ToolResultProvider,
)
from ..tool_results.repository import SampleRepository
from ..tool_results.validator import ToolResultValidator
from .event_recorder import EventRecorder
from .models import CaseRunStatus, RunEventType
from .repository import RunRepository
from .schemas import CaseRunDetail, RunEvent


class _Cancelled(Exception):
    pass


class CaseExecutor:
    def __init__(
        self,
        *,
        runs: RunRepository,
        evaluations: EvaluationRepository,
        samples: SampleRepository,
        drivers: DriverRegistry,
        secrets: SecretResolver,
        recorder: EventRecorder,
        validator: ToolResultValidator,
        simulation_curator: SimulationCurator,
        evidence_judge: EvidenceJudge,
        real_tool_client: RealToolClient | None = None,
        real_tool_allowlist: list[str] | None = None,
        rule_evaluator: RuleEvaluator | None = None,
        proxy_scopes: ProxyScopeRegistry | None = None,
        proxy_public_url: str = "",
        server_api_token: str | None = None,
    ) -> None:
        self._runs = runs
        self._evaluations = evaluations
        self._samples = samples
        self._drivers = drivers
        self._secrets = secrets
        self._recorder = recorder
        self._validator = validator
        self._simulation_curator = simulation_curator
        self._evidence_judge = evidence_judge
        self._real_tool_client = real_tool_client
        self._real_tool_allowlist = real_tool_allowlist or []
        self._rule_evaluator = rule_evaluator or RuleEvaluator()
        self._proxy_scopes = proxy_scopes
        self._proxy_public_url = proxy_public_url
        self._server_api_token = server_api_token

    async def execute(self, case_run_id: str, cancel_event: asyncio.Event) -> None:
        detail = await self._runs.get_case_run(case_run_id)
        assert detail is not None
        profile = ExecutionProfileConfig.model_validate(detail.profile_snapshot)
        driver: AgentDriver | None = None
        session: DriverSession | None = None
        proxy_scope: ProxyScope | None = None
        memory_events: list[RunEvent] = []
        try:
            await self._runs.set_case_run_status(case_run_id, CaseRunStatus.RUNNING)
            driver = self._drivers.create(
                str(detail.target_snapshot["driver_type"]),
                entrypoint=dict(detail.target_snapshot.get("options") or {}).get(
                    "entrypoint"
                ),
            )
            custom_providers: dict[ProviderName, ToolResultProvider] = {}
            if profile.curator_model is not None:
                custom_providers[ProviderName.SIMULATION_CURATOR] = SimulationCuratorProvider(
                    self._simulation_curator,
                    model_config=profile.curator_model,
                    timeout_seconds=profile.component_timeouts.curator,
                    validator=self._validator,
                )
            if self._real_tool_client is not None:
                custom_providers[ProviderName.REAL_TOOL] = RealToolProvider(
                    self._real_tool_client,
                    allowlist=self._real_tool_allowlist,
                    timeout_seconds=profile.component_timeouts.real_tool,
                )
            chain = build_provider_chain(
                profile.provider_chain,
                samples=self._samples,
                validator=self._validator,
                custom_providers=custom_providers,
            )
            proxy_headers: dict[str, str] = {}
            if profile.tool_mode is ToolMode.PROXY:
                if self._proxy_scopes is None or not self._proxy_public_url:
                    raise AgentRigError(
                        ErrorCode.VALIDATION_ERROR,
                        "proxy mode is not configured by this deployment",
                    )
                proxy_scope = self._proxy_scopes.register(
                    detail,
                    chain,
                    runs=self._runs,
                    recorder=self._recorder,
                )
                proxy_headers["X-AgentRig-Proxy-Scope"] = proxy_scope.token
                if self._server_api_token:
                    proxy_headers["Authorization"] = (
                        f"Bearer {self._server_api_token}"
                    )
            async with asyncio.timeout(profile.case_timeout_seconds):
                secret = self._secrets.resolve(detail.target_snapshot.get("secret_ref"))
                session = await driver.prepare(
                    DriverPrepareContext(
                        case_run_id=case_run_id,
                        target=detail.target_snapshot,
                        version=detail.version,
                        initial_state=dict(
                            detail.case_snapshot.get("initial_state") or {}
                        ),
                        secret_value=secret,
                        component_timeout_seconds=profile.component_timeouts.driver,
                        tool_proxy_url=(
                            self._proxy_public_url if proxy_scope is not None else None
                        ),
                        tool_proxy_headers=proxy_headers,
                    )
                )
                tool_call_count = await self._run_turns(
                    detail,
                    driver,
                    session,
                    chain,
                    cancel_event,
                    memory_events,
                    profile.tool_mode,
                    proxy_scope,
                )
                await self._evaluate_and_complete(
                    detail,
                    tool_call_count=tool_call_count,
                )
        except _Cancelled:
            if session is not None and driver is not None:
                await driver.cancel(session)
            await self._record_error(
                case_run_id,
                ErrorCode.CANCELLED.value,
                "case run cancelled",
            )
            await self._runs.set_case_run_status(
                case_run_id,
                CaseRunStatus.CANCELLED,
                error_code=ErrorCode.CANCELLED.value,
                error_message="case run cancelled",
            )
        except TimeoutError:
            await self._record_error(
                case_run_id,
                ErrorCode.CASE_TIMEOUT.value,
                f"case run exceeded {profile.case_timeout_seconds} seconds",
            )
            await self._runs.set_case_run_status(
                case_run_id,
                CaseRunStatus.FAILED,
                error_code=ErrorCode.CASE_TIMEOUT.value,
                error_message=f"case run exceeded {profile.case_timeout_seconds} seconds",
            )
        except AgentRigError as exc:
            await self._record_error(case_run_id, exc.detail.code.value, exc.detail.message)
            await self._runs.set_case_run_status(
                case_run_id,
                CaseRunStatus.FAILED,
                error_code=exc.detail.code.value,
                error_message=exc.detail.message,
            )
        except Exception as exc:
            await self._record_error(case_run_id, ErrorCode.INTERNAL_ERROR.value, str(exc))
            await self._runs.set_case_run_status(
                case_run_id,
                CaseRunStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                error_message=str(exc),
            )
        finally:
            if proxy_scope is not None and self._proxy_scopes is not None:
                self._proxy_scopes.revoke(proxy_scope.token)
            if session is not None and driver is not None:
                try:
                    await driver.close(session)
                except Exception:
                    # close 是清理动作，不应覆盖已经持久化的执行结论。
                    pass

    async def _run_turns(
        self,
        detail: CaseRunDetail,
        driver: AgentDriver,
        session: DriverSession,
        chain: ProviderChain,
        cancel_event: asyncio.Event,
        memory_events: list[RunEvent],
        tool_mode: ToolMode,
        proxy_scope: ProxyScope | None,
    ) -> int:
        tool_call_count = 0
        simulation_state: dict[str, Any] = {}
        for turn in detail.case_snapshot["turns"]:
            self._check_cancel(cancel_event)
            position = int(turn["position"])
            if proxy_scope is not None:
                proxy_scope.select_turn(position)
            memory_events.append(
                await self._recorder.record(
                    detail.id,
                    RunEventType.USER_MESSAGE,
                    {
                        "turn_position": position,
                        "text": str(turn["user_message"]),
                    },
                )
            )
            text_parts: list[str] = []
            pending_text_parts: list[str] = []
            pending_text_request_ids: list[str] = []
            pending_text_refusals: list[bool] = []
            first_action: list[str] = []
            refused: list[bool] = []
            tool_call_count = await self._consume_events(
                iterator=driver.send_user_message(session, str(turn["user_message"])),
                detail=detail,
                turn=turn,
                driver=driver,
                session=session,
                chain=chain,
                cancel_event=cancel_event,
                memory_events=memory_events,
                text_parts=text_parts,
                pending_text_parts=pending_text_parts,
                pending_text_request_ids=pending_text_request_ids,
                pending_text_refusals=pending_text_refusals,
                first_action=first_action,
                refused=refused,
                simulation_state=simulation_state,
                tool_call_count=tool_call_count,
                tool_mode=tool_mode,
            )
            memory_events.append(
                await self._recorder.record(
                    detail.id,
                    RunEventType.ASSISTANT_MESSAGE,
                    {
                        "turn_position": position,
                        "text": "".join(text_parts),
                        "refusal": any(refused),
                        **({"session_id": session.id} if session.id else {}),
                        **(
                            {"first_action": first_action[0]}
                            if first_action and tool_mode is not ToolMode.PROXY
                            else {}
                        ),
                    },
                )
            )
        return tool_call_count

    async def _consume_events(
        self,
        *,
        iterator: AsyncIterator[DriverEvent],
        detail: CaseRunDetail,
        turn: dict[str, Any],
        driver: AgentDriver,
        session: DriverSession,
        chain: ProviderChain,
        cancel_event: asyncio.Event,
        memory_events: list[RunEvent],
        text_parts: list[str],
        pending_text_parts: list[str],
        pending_text_request_ids: list[str],
        pending_text_refusals: list[bool],
        first_action: list[str],
        refused: list[bool],
        simulation_state: dict[str, Any],
        tool_call_count: int,
        tool_mode: ToolMode,
    ) -> int:
        results_to_inject: list[ToolResult] = []
        recorded_calls_to_resolve: list[tuple[ToolCall, RunEvent]] = []
        iterator_had_text_delta = False
        driver_error: AgentRigError | None = None
        iterator_error: Exception | None = None
        events: list[DriverEvent] = []
        try:
            async for event in iterator:
                self._check_cancel(cancel_event)
                events.append(event)
        except Exception as exc:
            iterator_error = exc

        for event in events:
            self._check_cancel(cancel_event)
            if event.type in {
                DriverEventType.REQUEST_STARTED,
                DriverEventType.REQUEST_COMPLETED,
            }:
                if event.type is DriverEventType.REQUEST_COMPLETED:
                    await self._flush_assistant_text(
                        detail=detail,
                        turn=turn,
                        memory_events=memory_events,
                        pending_text_parts=pending_text_parts,
                        pending_text_request_ids=pending_text_request_ids,
                        pending_text_refusals=pending_text_refusals,
                    )
                payload: dict[str, Any] = {
                    "turn_position": int(turn["position"]),
                    "phase": (
                        "started"
                        if event.type is DriverEventType.REQUEST_STARTED
                        else "completed"
                    ),
                    "request_id": event.request_id,
                    "request_kind": event.request_kind,
                }
                if event.request_status is not None:
                    payload["status"] = event.request_status
                if event.duration_ms is not None:
                    payload["duration_ms"] = event.duration_ms
                if event.ttft_ms is not None:
                    payload["ttft_ms"] = event.ttft_ms
                memory_events.append(
                    await self._recorder.record(
                        detail.id,
                        RunEventType.DRIVER_REQUEST,
                        payload,
                    )
                )
            elif event.type is DriverEventType.SESSION_STARTED:
                if event.session_id:
                    memory_events.append(
                        await self._recorder.record(
                            detail.id,
                            RunEventType.DRIVER_SESSION,
                            {
                                "turn_position": int(turn["position"]),
                                "session_id": event.session_id,
                                **(
                                    {"request_id": event.request_id}
                                    if event.request_id
                                    else {}
                                ),
                            },
                        )
                    )
            elif event.type is DriverEventType.ASSISTANT_TEXT_DELTA:
                text = event.text or ""
                text_parts.append(text)
                pending_text_parts.append(text)
                if event.request_id:
                    pending_text_request_ids.append(event.request_id)
                iterator_had_text_delta = iterator_had_text_delta or bool(text)
                if text and not first_action:
                    first_action.append("text")
            elif event.type is DriverEventType.ASSISTANT_MESSAGE_COMPLETED:
                if event.text and not iterator_had_text_delta:
                    text_parts.append(event.text)
                    pending_text_parts.append(event.text)
                    if event.request_id:
                        pending_text_request_ids.append(event.request_id)
                if event.refusal:
                    refused.append(True)
                    pending_text_refusals.append(True)
                if (event.text or event.refusal) and not first_action:
                    first_action.append("refuse" if event.refusal else "text")
            elif event.type is DriverEventType.USAGE:
                await self._flush_assistant_text(
                    detail=detail,
                    turn=turn,
                    memory_events=memory_events,
                    pending_text_parts=pending_text_parts,
                    pending_text_request_ids=pending_text_request_ids,
                    pending_text_refusals=pending_text_refusals,
                )
                memory_events.append(
                    await self._recorder.record(
                        detail.id,
                        RunEventType.USAGE,
                        {
                            "turn_position": int(turn["position"]),
                            **event.usage,
                        },
                    )
                )
            elif event.type is DriverEventType.ERROR:
                await self._flush_assistant_text(
                    detail=detail,
                    turn=turn,
                    memory_events=memory_events,
                    pending_text_parts=pending_text_parts,
                    pending_text_request_ids=pending_text_request_ids,
                    pending_text_refusals=pending_text_refusals,
                )
                driver_error = AgentRigError(
                    ErrorCode.TARGET_UNREACHABLE,
                    event.error or "driver returned an error",
                    retryable=True,
                )
            elif event.type is DriverEventType.TOOL_CALLS:
                await self._flush_assistant_text(
                    detail=detail,
                    turn=turn,
                    memory_events=memory_events,
                    pending_text_parts=pending_text_parts,
                    pending_text_request_ids=pending_text_request_ids,
                    pending_text_refusals=pending_text_refusals,
                )
                if event.tool_calls and not first_action:
                    first_action.append("tool")
                tool_call_count += len(event.tool_calls)
                if tool_call_count > 50:
                    raise AgentRigError(
                        ErrorCode.VALIDATION_ERROR,
                        "case run exceeded 50 tool calls",
                    )
                if tool_mode is ToolMode.CONTROLLED:
                    for call in event.tool_calls:
                        call_event = await self._recorder.record(
                            detail.id,
                            RunEventType.TOOL_CALL,
                            {
                                "turn_position": int(turn["position"]),
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "arguments": call.arguments,
                                "result_schema": call.result_schema,
                                **(
                                    {"request_id": event.request_id}
                                    if event.request_id
                                    else {}
                                ),
                            },
                        )
                        memory_events.append(call_event)
                        recorded_calls_to_resolve.append((call, call_event))
                else:
                    for call in event.tool_calls:
                        memory_events.append(
                            await self._recorder.record(
                                detail.id,
                                RunEventType.TOOL_CALL,
                                {
                                    "turn_position": int(turn["position"]),
                                    "tool_call_id": call.id,
                                    "tool_name": call.name,
                                    "arguments": call.arguments,
                                    "observed_only": True,
                                    **(
                                        {"request_id": event.request_id}
                                        if event.request_id
                                        else {}
                                    ),
                                },
                            )
                        )
        await self._flush_assistant_text(
            detail=detail,
            turn=turn,
            memory_events=memory_events,
            pending_text_parts=pending_text_parts,
            pending_text_request_ids=pending_text_request_ids,
            pending_text_refusals=pending_text_refusals,
        )
        if iterator_error is not None:
            raise iterator_error
        if driver_error is not None:
            raise driver_error
        if recorded_calls_to_resolve:
            results_to_inject.extend(
                await self._resolve_tool_calls(
                    detail=detail,
                    turn=turn,
                    calls=recorded_calls_to_resolve,
                    chain=chain,
                    memory_events=memory_events,
                    simulation_state=simulation_state,
                )
            )
        if results_to_inject:
            tool_call_count = await self._consume_events(
                iterator=driver.send_tool_results(session, results_to_inject),
                detail=detail,
                turn=turn,
                driver=driver,
                session=session,
                chain=chain,
                cancel_event=cancel_event,
                memory_events=memory_events,
                text_parts=text_parts,
                pending_text_parts=pending_text_parts,
                pending_text_request_ids=pending_text_request_ids,
                pending_text_refusals=pending_text_refusals,
                first_action=first_action,
                refused=refused,
                simulation_state=simulation_state,
                tool_call_count=tool_call_count,
                tool_mode=tool_mode,
            )
        return tool_call_count

    async def _flush_assistant_text(
        self,
        *,
        detail: CaseRunDetail,
        turn: dict[str, Any],
        memory_events: list[RunEvent],
        pending_text_parts: list[str],
        pending_text_request_ids: list[str],
        pending_text_refusals: list[bool],
    ) -> None:
        if not pending_text_parts and not pending_text_refusals:
            return
        request_id = (
            pending_text_request_ids[0] if pending_text_request_ids else None
        )
        memory_events.append(
            await self._recorder.record(
                detail.id,
                RunEventType.ASSISTANT_TEXT,
                {
                    "turn_position": int(turn["position"]),
                    "text": "".join(pending_text_parts),
                    "refusal": any(pending_text_refusals),
                    **({"request_id": request_id} if request_id else {}),
                },
            )
        )
        pending_text_parts.clear()
        pending_text_request_ids.clear()
        pending_text_refusals.clear()

    async def _resolve_tool_calls(
        self,
        *,
        detail: CaseRunDetail,
        turn: dict[str, Any],
        calls: list[tuple[ToolCall, RunEvent]],
        chain: ProviderChain,
        memory_events: list[RunEvent],
        simulation_state: dict[str, Any],
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call, call_event in calls:
            context = ProviderContext(
                case_run_id=detail.id,
                turn_position=int(turn["position"]),
                tool_call=call,
                fixtures=turn.get("fixtures", []),
                version=detail.version,
                initial_state=dict(detail.case_snapshot.get("initial_state") or {}),
                simulation_instruction=turn.get("simulation_instruction"),
                prior_events=[item.model_dump(mode="json") for item in memory_events],
                simulation_state=simulation_state,
            )
            try:
                resolution = await chain.resolve(context)
            except ProviderExhausted as exc:
                await self._record_attempts(detail.id, call, exc.attempts, memory_events)
                if exc.validation_errors:
                    memory_events.append(
                        await self._recorder.record(
                            detail.id,
                            RunEventType.VALIDATION,
                            {
                                "turn_position": int(turn["position"]),
                                "tool_call_id": call.id,
                                "valid": False,
                                "errors": exc.validation_errors,
                            },
                        )
                    )
                raise
            await self._record_attempts(detail.id, call, resolution.attempts, memory_events)
            memory_events.append(
                await self._recorder.record(
                    detail.id,
                    RunEventType.VALIDATION,
                    {
                        "turn_position": int(turn["position"]),
                        "tool_call_id": call.id,
                        "valid": True,
                        "errors": [],
                    },
                )
            )
            result = resolution.result
            state_updates = result.metadata.get("state_updates")
            if isinstance(state_updates, dict):
                simulation_state.update(state_updates)
            memory_events.append(
                await self._recorder.record(
                    detail.id,
                    RunEventType.TOOL_RESULT,
                    {
                        "turn_position": int(turn["position"]),
                        "tool_call_id": call.id,
                        "tool_call_event_id": call_event.id,
                        "tool_name": call.name,
                        "result": result.result,
                        "source": result.source,
                        "metadata": result.metadata,
                    },
                )
            )
            results.append(result)
        return results

    async def _record_attempts(
        self,
        case_run_id: str,
        call: ToolCall,
        attempts: list[ProviderAttempt],
        memory_events: list[RunEvent],
    ) -> None:
        for attempt in attempts:
            memory_events.append(
                await self._recorder.record(
                    case_run_id,
                    RunEventType.PROVIDER_ATTEMPT,
                    {
                        "tool_call_id": call.id,
                        **attempt.model_dump(mode="json"),
                    },
                )
            )

    async def _evaluate_and_complete(
        self,
        original: CaseRunDetail,
        *,
        tool_call_count: int,
    ) -> None:
        detail = await self._runs.get_case_run(original.id)
        assert detail is not None
        tool_call_count = sum(
            event.event_type is RunEventType.TOOL_CALL for event in detail.events
        )
        assertions = detail.case_snapshot.get("case_assertions", []) or [
            assertion
            for turn in detail.case_snapshot["turns"]
            for assertion in turn.get("assertions", [])
        ]
        rule_verdict: str | None = None
        rule_result: EvaluationResult | None = None
        if assertions:
            draft = self._rule_evaluator.evaluate(detail.case_snapshot, detail.events)
            rule_verdict = draft.verdict
            rule_result = await self._evaluations.upsert(
                case_run_id=detail.id,
                evaluator_type=EvaluatorType.RULE,
                evaluator_source="agentrig.rule.v1",
                status=draft.status,
                verdict=draft.verdict,
                summary=draft.summary,
                criteria=draft.criteria,
                evidence_refs=draft.evidence_refs,
                config_snapshot=draft.config_snapshot,
                model_metadata=draft.model_metadata,
            )
        if detail.primary_evaluator is EvaluatorType.RULE:
            outcome = EvaluationOutcome.PASS if rule_verdict == "pass" else EvaluationOutcome.FAIL
        elif detail.primary_evaluator is EvaluatorType.EXTERNAL_CONTROLLER:
            outcome = EvaluationOutcome.AWAITING_VERDICT
        else:
            profile = ExecutionProfileConfig.model_validate(detail.profile_snapshot)
            if profile.judge_model is not None:
                judge_draft = await self._evidence_judge.evaluate(
                    detail,
                    rule_result=rule_result,
                    model_config=profile.judge_model,
                    timeout_seconds=profile.component_timeouts.judge,
                )
            else:
                judge_draft = EvaluationDraft(
                    status=EvaluationRecordStatus.ERROR,
                    verdict=None,
                    summary="Evidence Judge model is not configured",
                )
            await self._evaluations.upsert(
                case_run_id=detail.id,
                evaluator_type=EvaluatorType.EVIDENCE_JUDGE,
                evaluator_source="agentrig.evidence_judge.v1",
                status=judge_draft.status,
                verdict=judge_draft.verdict,
                summary=judge_draft.summary,
                criteria=judge_draft.criteria,
                evidence_refs=judge_draft.evidence_refs,
                config_snapshot=judge_draft.config_snapshot,
                model_metadata=judge_draft.model_metadata,
            )
            outcome = (
                EvaluationOutcome(judge_draft.verdict)
                if judge_draft.verdict is not None
                else EvaluationOutcome.EVALUATION_ERROR
            )
        await self._runs.set_case_run_status(
            detail.id,
            CaseRunStatus.COMPLETED,
            evaluation_state=outcome,
            summary={
                "turn_count": len(detail.case_snapshot["turns"]),
                "tool_call_count": tool_call_count,
            },
        )

    async def _record_error(self, case_run_id: str, code: str, message: str) -> None:
        await self._recorder.record(
            case_run_id,
            RunEventType.ERROR,
            {"code": code, "message": message},
        )

    @staticmethod
    def _check_cancel(event: asyncio.Event) -> None:
        if event.is_set():
            raise _Cancelled
