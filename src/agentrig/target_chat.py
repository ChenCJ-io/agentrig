"""面向工作台的可持久化 Target 直连会话。

直连会话用于人工探索被测 Agent，不产生 Run、CaseRun 或权威 Evaluation。它复用
Driver 和 ToolResult Provider Chain，但 Simulation Curator 使用本地模型端口；正式
评测中的 Curator/Judge 仍由 CaseExecutor 和 AgentTeams 调度并完整持久化。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .agents import SimulationCurator
from .cases import CaseService, TestCaseCreate, TestCaseView
from .errors import AgentRigError, ErrorCode
from .identifiers import new_id
from .infrastructure.secrets import SecretResolver
from .profiles.models import ProviderName, ToolMode
from .profiles.schemas import ExecutionProfileConfig, ProfileView
from .profiles.service import ProfileService
from .runs.redactor import Redactor
from .target_chat_repository import TargetChatRepository
from .targets.drivers import (
    AgentDriver,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)
from .targets.options import merge_target_options
from .targets.service import TargetService
from .tool_results.chain import ProviderChain, ProviderExhausted, build_provider_chain
from .tool_results.providers import (
    ProviderContext,
    RealToolClient,
    RealToolProvider,
    SimulationCuratorProvider,
    ToolResultProvider,
)
from .tool_results.repository import SampleRepository
from .tool_results.schemas import SampleCreate, SampleView
from .tool_results.service import SampleService
from .tool_results.validator import ToolResultValidator


class TargetChatCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1)
    profile_id: str | None = None
    version: str | None = None


class TargetChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)


class TargetChatEvent(BaseModel):
    seq: int
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TargetChatView(BaseModel):
    id: str
    target_id: str
    profile_id: str | None
    version: str | None
    status: str
    events: list[TargetChatEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TargetChatPage(BaseModel):
    items: list[TargetChatView]
    total: int
    limit: int
    offset: int


class TargetChatDraftCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=300)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    primary_evaluator: str = "rule"


class TargetChatDraftSampleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=300)


@dataclass
class _TargetChatState:
    id: str
    target_id: str
    profile: ProfileView
    version: str | None
    driver: AgentDriver
    driver_session: DriverSession
    chain: ProviderChain
    initial_state: dict[str, Any]
    status: str = "open"
    events: list[TargetChatEvent] = field(default_factory=list)
    simulation_state: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class TargetChatService:
    """活跃 Driver 会话驻留进程，脱敏后的会话历史持久化到数据库。"""

    def __init__(
        self,
        *,
        targets: TargetService,
        cases: CaseService,
        profiles: ProfileService,
        drivers: DriverRegistry,
        secrets: SecretResolver,
        samples: SampleRepository,
        sample_service: SampleService,
        repository: TargetChatRepository,
        validator: ToolResultValidator,
        curator: SimulationCurator,
        redactor: Redactor,
        real_tool_client: RealToolClient | None = None,
        real_tool_allowlist: list[str] | None = None,
    ) -> None:
        self._targets = targets
        self._cases = cases
        self._profiles = profiles
        self._drivers = drivers
        self._secrets = secrets
        self._samples = samples
        self._sample_service = sample_service
        self._repository = repository
        self._validator = validator
        self._curator = curator
        self._redactor = redactor
        self._real_tool_client = real_tool_client
        self._real_tool_allowlist = real_tool_allowlist or []
        self._sessions: dict[str, _TargetChatState] = {}
        self._sessions_lock = asyncio.Lock()

    async def create(self, value: TargetChatCreate) -> TargetChatView:
        target = await self._targets.get(value.target_id)
        profile = await self._resolve_profile(value.profile_id)
        config = profile.config
        if config.tool_mode is ToolMode.PROXY:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "direct Target conversation does not support proxy tool mode",
            )

        version_config = None
        version = value.version
        if version is None and target.versions:
            version = target.versions[0].version
        if version is not None:
            version_config = next(
                (item for item in target.versions if item.version == version),
                None,
            )
            if version_config is None:
                raise AgentRigError(
                    ErrorCode.VERSION_INCOMPATIBLE,
                    f"target version is not configured: {version}",
                    details={"target_id": target.id, "version": version},
                )

        endpoint = (
            version_config.endpoint
            if version_config is not None and version_config.endpoint is not None
            else target.endpoint
        )
        options = merge_target_options(
            target.options,
            version_config.options if version_config is not None else {},
        )
        initial_state_value = options.get("conversation_initial_state", {})
        if not isinstance(initial_state_value, dict):
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "target options.conversation_initial_state must be an object",
            )
        initial_state = dict(initial_state_value)
        target_snapshot = {
            "id": target.id,
            "name": target.name,
            "driver_type": target.driver_type,
            "endpoint": endpoint,
            "options": options,
            "secret_ref": target.secret_ref,
        }
        driver = self._drivers.create(
            target.driver_type,
            entrypoint=(str(options["entrypoint"]) if options.get("entrypoint") else None),
        )
        capabilities = driver.capabilities()
        if not capabilities.multi_turn:
            raise AgentRigError(
                ErrorCode.DRIVER_CAPABILITY_MISSING,
                "direct Target conversation requires a multi-turn driver",
            )
        if config.tool_mode is ToolMode.CONTROLLED and not capabilities.tool_result_injection:
            raise AgentRigError(
                ErrorCode.DRIVER_CAPABILITY_MISSING,
                "controlled conversation requires tool result injection",
            )

        chain = self._build_chain(config)
        chat_id = new_id("targetchat")
        try:
            driver_session = await driver.prepare(
                DriverPrepareContext(
                    case_run_id=chat_id,
                    target=target_snapshot,
                    version=version,
                    initial_state=initial_state,
                    secret_value=self._secrets.resolve(target.secret_ref),
                    component_timeout_seconds=config.component_timeouts.driver,
                )
            )
        except AgentRigError:
            raise
        except Exception as exc:
            raise AgentRigError(
                ErrorCode.TARGET_UNREACHABLE,
                f"failed to prepare Target conversation: {exc}",
                retryable=True,
            ) from exc

        state = _TargetChatState(
            id=chat_id,
            target_id=target.id,
            profile=profile,
            version=version,
            driver=driver,
            driver_session=driver_session,
            chain=chain,
            initial_state=initial_state,
        )
        self._record(
            state,
            "session_started",
            {
                "target_id": target.id,
                "profile_id": profile.id,
                "version": version,
                "tool_mode": config.tool_mode.value,
                "driver_type": target.driver_type,
                "driver_session_id": driver_session.id,
            },
        )
        async with self._sessions_lock:
            self._sessions[chat_id] = state
        view = self._view(state)
        await self._repository.save(view)
        return view

    async def get(self, chat_id: str) -> TargetChatView:
        async with self._sessions_lock:
            state = self._sessions.get(chat_id)
        if state is not None:
            return self._view(state)
        value = await self._repository.get(chat_id)
        if value is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"Target conversation not found: {chat_id}",
                details={"chat_id": chat_id},
            )
        return value

    async def list_sessions(
        self,
        *,
        target_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TargetChatPage:
        return await self._repository.list_page(
            target_id=target_id,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def send(self, chat_id: str, value: TargetChatMessage) -> TargetChatView:
        state = await self._get_state(chat_id)
        async with state.lock:
            try:
                if state.status != "open":
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        f"Target conversation is not open: {state.status}",
                    )
                self._record(state, "user_message", {"content": value.content})
                text_parts: list[str] = []
                try:
                    async with asyncio.timeout(state.profile.config.case_timeout_seconds):
                        await self._consume_events(
                            state,
                            state.driver.send_user_message(
                                state.driver_session,
                                value.content,
                            ),
                            text_parts,
                            tool_call_count=0,
                        )
                except AgentRigError as exc:
                    self._record(
                        state,
                        "error",
                        {
                            "code": exc.detail.code.value,
                            "message": exc.detail.message,
                            "retryable": exc.detail.retryable,
                        },
                    )
                    raise
                except TimeoutError as exc:
                    error = AgentRigError(
                        ErrorCode.CASE_TIMEOUT,
                        "direct Target conversation turn timed out",
                        retryable=True,
                    )
                    self._record(
                        state,
                        "error",
                        {"code": error.detail.code.value, "message": error.detail.message},
                    )
                    raise error from exc
                except Exception as exc:
                    error = AgentRigError(
                        ErrorCode.TARGET_UNREACHABLE,
                        f"Target conversation failed: {exc}",
                        retryable=True,
                    )
                    self._record(
                        state,
                        "error",
                        {"code": error.detail.code.value, "message": error.detail.message},
                    )
                    raise error from exc
                self._record(
                    state,
                    "assistant_message",
                    {
                        "text": "".join(text_parts),
                        "driver_session_id": state.driver_session.id,
                    },
                )
                return self._view(state)
            finally:
                await self._repository.save(self._view(state))

    async def close(self, chat_id: str) -> TargetChatView:
        state = await self._get_state(chat_id)
        async with state.lock:
            if state.status == "open":
                try:
                    await state.driver.close(state.driver_session)
                finally:
                    state.status = "closed"
                    self._record(state, "session_closed", {})
            view = self._view(state)
            await self._repository.save(view)
            return view

    async def create_draft_case(
        self,
        chat_id: str,
        value: TargetChatDraftCaseCreate,
    ) -> TestCaseView:
        chat = await self.get(chat_id)
        turns: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        tool_results = {
            str(event.payload.get("tool_call_id")): event.payload
            for event in chat.events
            if event.event_type == "tool_result"
        }
        for event in chat.events:
            if event.event_type == "user_message":
                if current is not None:
                    turns.append(current)
                current = {
                    "position": len(turns) + 1,
                    "user_message": str(event.payload.get("content", "")),
                    "fixtures": [],
                    "assertions": [{"kind": "no_execution_error"}],
                }
                continue
            if event.event_type != "tool_call" or current is None:
                continue
            call_id = str(event.payload.get("tool_call_id", ""))
            result = tool_results.get(call_id)
            tool_name = str(event.payload.get("tool_name", ""))
            if tool_name:
                current["assertions"].append(
                    {"kind": "tool_called", "tool_name": tool_name}
                )
            if result is not None and tool_name:
                current["fixtures"].append(
                    {
                        "tool_name": tool_name,
                        "match_arguments": event.payload.get("arguments", {}),
                        "result": result.get("result"),
                    }
                )
        if current is not None:
            turns.append(current)
        if not turns:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "Target conversation has no user turn to convert",
            )
        return await self._cases.create(
            TestCaseCreate.model_validate(
                {
                    "name": value.name or f"对话回归 · {chat.id[-8:]}",
                    "description": value.description
                    or f"由 Target 直连会话 {chat.id} 生成，提交审核前请确认断言。",
                    "tags": [*value.tags, "source.target_chat"],
                    "supported_versions": [chat.version] if chat.version else [],
                    "primary_evaluator": value.primary_evaluator,
                    "turns": turns,
                }
            )
        )

    async def create_draft_sample(
        self,
        chat_id: str,
        value: TargetChatDraftSampleCreate,
    ) -> SampleView:
        chat = await self.get(chat_id)
        call = next(
            (
                event
                for event in chat.events
                if event.event_type == "tool_call"
                and event.payload.get("tool_call_id") == value.tool_call_id
            ),
            None,
        )
        result = next(
            (
                event
                for event in chat.events
                if event.event_type == "tool_result"
                and event.payload.get("tool_call_id") == value.tool_call_id
            ),
            None,
        )
        if call is None or result is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"complete ToolCall evidence not found: {value.tool_call_id}",
            )
        arguments = call.payload.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        ignored_paths = _redacted_paths(arguments)
        tool_name = str(call.payload.get("tool_name", ""))
        return await self._sample_service.create(
            SampleCreate(
                name=value.name or f"{tool_name} · 对话样本 {chat.id[-8:]}",
                tool_name=tool_name,
                content=result.payload.get("result"),
                match_arguments=_without_redacted(arguments),
                ignored_argument_paths=ignored_paths,
                supported_versions=[chat.version] if chat.version else [],
            )
        )

    async def close_all(self) -> None:
        async with self._sessions_lock:
            states = list(self._sessions.values())
        for state in states:
            if state.status != "open":
                continue
            try:
                await state.driver.close(state.driver_session)
            except Exception:
                pass
            state.status = "closed"
            state.updated_at = datetime.now(UTC)
            await self._repository.save(self._view(state))

    async def mark_interrupted(self) -> int:
        return await self._repository.mark_open_interrupted()

    async def _consume_events(
        self,
        state: _TargetChatState,
        iterator: AsyncIterator[DriverEvent],
        text_parts: list[str],
        *,
        tool_call_count: int,
    ) -> int:
        calls: list[ToolCall] = []
        iterator_had_delta = False
        driver_error: str | None = None
        async for event in iterator:
            if event.type is DriverEventType.REQUEST_STARTED:
                self._record(
                    state,
                    "driver_request",
                    {
                        "phase": "started",
                        "request_id": event.request_id,
                        "request_kind": event.request_kind,
                    },
                )
            elif event.type is DriverEventType.REQUEST_COMPLETED:
                self._record(
                    state,
                    "driver_request",
                    {
                        "phase": "completed",
                        "request_id": event.request_id,
                        "request_kind": event.request_kind,
                        "status": event.request_status,
                        "duration_ms": event.duration_ms,
                        "ttft_ms": event.ttft_ms,
                    },
                )
            elif event.type is DriverEventType.SESSION_STARTED:
                self._record(
                    state,
                    "driver_session",
                    {"session_id": event.session_id, "request_id": event.request_id},
                )
            elif event.type is DriverEventType.ASSISTANT_TEXT_DELTA:
                text = event.text or ""
                if text:
                    iterator_had_delta = True
                    text_parts.append(text)
                    self._record(
                        state,
                        "assistant_text",
                        {"text": text, "request_id": event.request_id},
                    )
            elif event.type is DriverEventType.ASSISTANT_MESSAGE_COMPLETED:
                if event.text and not iterator_had_delta:
                    text_parts.append(event.text)
                    self._record(
                        state,
                        "assistant_text",
                        {
                            "text": event.text,
                            "request_id": event.request_id,
                            "refusal": event.refusal,
                        },
                    )
            elif event.type is DriverEventType.TOOL_CALLS:
                calls.extend(event.tool_calls)
                tool_call_count += len(event.tool_calls)
                if tool_call_count > 50:
                    raise AgentRigError(
                        ErrorCode.VALIDATION_ERROR,
                        "direct Target conversation exceeded 50 tool calls",
                    )
                for call in event.tool_calls:
                    self._record(
                        state,
                        "tool_call",
                        {
                            "tool_call_id": call.id,
                            "tool_name": call.name,
                            "arguments": call.arguments,
                            "result_schema": call.result_schema,
                            "request_id": event.request_id,
                            "observed_only": (
                                state.profile.config.tool_mode is ToolMode.OBSERVE_ONLY
                            ),
                        },
                    )
            elif event.type is DriverEventType.USAGE:
                self._record(state, "usage", event.usage)
            elif event.type is DriverEventType.ERROR:
                driver_error = event.error or "driver returned an error"
        if driver_error is not None:
            raise AgentRigError(
                ErrorCode.TARGET_UNREACHABLE,
                driver_error,
                retryable=True,
            )
        if not calls or state.profile.config.tool_mode is ToolMode.OBSERVE_ONLY:
            return tool_call_count

        results = await self._resolve_tool_calls(state, calls)
        return await self._consume_events(
            state,
            state.driver.send_tool_results(state.driver_session, results),
            text_parts,
            tool_call_count=tool_call_count,
        )

    async def _resolve_tool_calls(
        self,
        state: _TargetChatState,
        calls: list[ToolCall],
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            context = ProviderContext(
                case_run_id=state.id,
                turn_position=self._user_turn_count(state),
                tool_call=call,
                version=state.version,
                initial_state=state.initial_state,
                prior_events=[event.model_dump(mode="json") for event in state.events],
                simulation_state=state.simulation_state,
            )
            try:
                resolution = await state.chain.resolve(context)
            except ProviderExhausted as exc:
                self._record_attempts(state, call, exc.attempts)
                raise
            self._record_attempts(state, call, resolution.attempts)
            result = resolution.result
            state_updates = result.metadata.get("state_updates")
            if isinstance(state_updates, dict):
                state.simulation_state.update(state_updates)
            self._record(
                state,
                "validation",
                {"tool_call_id": call.id, "valid": True, "errors": []},
            )
            self._record(
                state,
                "tool_result",
                {
                    "tool_call_id": call.id,
                    "tool_name": call.name,
                    "result": result.result,
                    "source": result.source,
                    "metadata": result.metadata,
                },
            )
            results.append(result)
        return results

    def _record_attempts(
        self,
        state: _TargetChatState,
        call: ToolCall,
        attempts: list[Any],
    ) -> None:
        for attempt in attempts:
            self._record(
                state,
                "provider_attempt",
                {"tool_call_id": call.id, **attempt.model_dump(mode="json")},
            )

    def _build_chain(self, config: ExecutionProfileConfig) -> ProviderChain:
        custom: dict[ProviderName, ToolResultProvider] = {}
        if config.curator_model is not None:
            custom[ProviderName.SIMULATION_CURATOR] = SimulationCuratorProvider(
                self._curator,
                model_config=config.curator_model,
                timeout_seconds=config.component_timeouts.curator,
                validator=self._validator,
            )
        if self._real_tool_client is not None:
            custom[ProviderName.REAL_TOOL] = RealToolProvider(
                self._real_tool_client,
                allowlist=self._real_tool_allowlist,
                timeout_seconds=config.component_timeouts.real_tool,
            )
        return build_provider_chain(
            config.provider_chain,
            samples=self._samples,
            validator=self._validator,
            custom_providers=custom,
        )

    async def _resolve_profile(self, profile_id: str | None) -> ProfileView:
        if profile_id is not None:
            return await self._profiles.get(profile_id)
        page = await self._profiles.list_profiles(limit=1)
        if not page.items:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                "create an Execution Profile before starting a Target conversation",
            )
        return page.items[0]

    async def _get_state(self, chat_id: str) -> _TargetChatState:
        async with self._sessions_lock:
            state = self._sessions.get(chat_id)
        if state is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"Target conversation not found: {chat_id}",
                details={"chat_id": chat_id},
            )
        return state

    def _record(
        self,
        state: _TargetChatState,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        state.events.append(
            TargetChatEvent(
                seq=len(state.events) + 1,
                event_type=event_type,
                payload=self._redactor.redact(payload),
                created_at=now,
            )
        )
        state.updated_at = now

    @staticmethod
    def _user_turn_count(state: _TargetChatState) -> int:
        return sum(event.event_type == "user_message" for event in state.events)

    @staticmethod
    def _view(state: _TargetChatState) -> TargetChatView:
        return TargetChatView(
            id=state.id,
            target_id=state.target_id,
            profile_id=state.profile.id,
            version=state.version,
            status=state.status,
            events=[event.model_copy(deep=True) for event in state.events],
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


def _redacted_paths(value: Any, prefix: str = "") -> list[str]:
    """将脱敏占位值转为 Sample matcher 的忽略路径。"""

    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if child == "[REDACTED]":
                paths.append(path)
            else:
                paths.extend(_redacted_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            paths.extend(_redacted_paths(child, path))
    return paths


def _without_redacted(value: dict[str, Any]) -> dict[str, Any]:
    """从 Sample 内容中完全移除脱敏字段，避免占位符被误存为数据。"""

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: clean(child)
                for key, child in item.items()
                if child != "[REDACTED]"
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        return item

    cleaned = clean(value)
    assert isinstance(cleaned, dict)
    return cleaned
