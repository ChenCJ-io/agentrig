"""Deterministic state machine behind the public reference target."""

from dataclasses import dataclass, field
from typing import Any

from examples.reference_target.schemas import (
    ChatStreamRequest,
    ReferenceScenario,
    ReferenceVersion,
)

SCENARIO_CATALOG: tuple[dict[str, str], ...] = (
    {
        "id": "reference_success",
        "purpose": "Prove a normal tool-call path can pass reproducibly.",
    },
    {
        "id": "reference_policy_regression",
        "purpose": "Make the candidate violate confirmation-before-action policy.",
    },
    {
        "id": "reference_recovery",
        "purpose": "Fail attempt 1 with HTTP 503 and pass an explicit attempt 2.",
    },
)


@dataclass(frozen=True)
class SseEvent:
    """One logical event serialized onto an SSE stream."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data}


@dataclass(frozen=True)
class ReferenceExchange:
    """Result produced by the deterministic state machine."""

    status_code: int = 200
    events: tuple[SseEvent, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ReferenceSession:
    """Minimal server-side state needed across chat and tool-result calls."""

    id: str
    scenario: ReferenceScenario
    version: ReferenceVersion
    stage: str
    expected_tool: str | None = None
    request_count: int = 0


class ReferenceEngine:
    """In-memory deterministic engine; intended for a single demo process."""

    def __init__(self) -> None:
        self._next_session_number = 1
        self._sessions: dict[str, ReferenceSession] = {}

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    def handle(self, request: ChatStreamRequest) -> ReferenceExchange:
        session_before = self._sessions.get(request.session_id or "")
        if session_before is not None:
            session_before.request_count += 1
            request_number = session_before.request_count
            request_session_id = session_before.id
        else:
            request_number = 1
            request_session_id = None

        if request.type == "tool_result":
            exchange = self._handle_tool_result(request)
        elif request.session_id:
            exchange = self._handle_follow_up_chat(request)
        else:
            exchange = self._handle_initial_chat(request)

        if exchange.status_code != 200:
            return exchange
        if request_session_id is None:
            request_session_id = self._session_id_from(exchange)
            created_session = self._sessions.get(request_session_id or "")
            if created_session is not None:
                created_session.request_count = request_number
        if request_session_id is None:
            return self._protocol_error(
                500,
                "missing_reference_session",
                "successful exchange did not create a session",
            )
        request_id = f"{request_session_id}:{request.type}:request-{request_number:02d}"
        return self._with_request_boundary(exchange, request_id, request.type)

    def _handle_initial_chat(self, request: ChatStreamRequest) -> ReferenceExchange:
        config = request.reference_config()
        version: ReferenceVersion = request.version or "baseline"

        if config.scenario == "reference_recovery" and config.attempt == 1:
            return ReferenceExchange(
                status_code=503,
                error_code="reference_transient_failure",
                error_message="deterministic recovery attempt 1 failure",
            )

        session = self._new_session(config.scenario, version)
        events = [self._session_event(session)]

        if config.scenario == "reference_success":
            session.stage = "awaiting_tool_result"
            session.expected_tool = "reference_lookup"
            events.append(
                self._tool_call_event(
                    session,
                    name="reference_lookup",
                    arguments={"query": "AgentRig"},
                )
            )
            return ReferenceExchange(events=tuple(events))

        if config.scenario == "reference_policy_regression":
            if version == "candidate-regression":
                session.stage = "regression_awaiting_tool_result"
                session.expected_tool = "apply_image_prompt"
                events.append(
                    self._tool_call_event(
                        session,
                        name="apply_image_prompt",
                        arguments={"prompt": "reference-safe-change"},
                    )
                )
            else:
                session.stage = "awaiting_confirmation"
                events.extend(
                    self._text_events("Confirmation required before applying the change.")
                )
            return ReferenceExchange(events=tuple(events))

        session.stage = "awaiting_tool_result"
        session.expected_tool = "reference_healthcheck"
        events.append(
            self._tool_call_event(
                session,
                name="reference_healthcheck",
                arguments={"attempt": config.attempt},
            )
        )
        return ReferenceExchange(events=tuple(events))

    def _handle_follow_up_chat(self, request: ChatStreamRequest) -> ReferenceExchange:
        session = self._sessions.get(request.session_id or "")
        if session is None:
            return self._protocol_error(404, "unknown_session", "session does not exist")
        if request.version is not None and request.version != session.version:
            return self._protocol_error(
                409,
                "version_mismatch",
                "request version does not match the active session",
            )
        if session.scenario != "reference_policy_regression":
            return self._protocol_error(
                409,
                "unexpected_follow_up",
                "this scenario does not accept a follow-up chat message",
            )

        if session.stage == "awaiting_confirmation":
            if not self._is_confirmation(request.message or ""):
                return ReferenceExchange(
                    events=tuple(self._text_events("Confirmation still required before applying."))
                )
            session.stage = "awaiting_tool_result"
            session.expected_tool = "apply_image_prompt"
            return ReferenceExchange(
                events=(
                    self._tool_call_event(
                        session,
                        name="apply_image_prompt",
                        arguments={"prompt": "reference-safe-change"},
                    ),
                )
            )

        if session.stage == "regression_applied":
            self._sessions.pop(session.id, None)
            return ReferenceExchange(
                events=tuple(
                    self._text_events(
                        "Change was already applied before confirmation.",
                        include_usage=True,
                    )
                )
            )

        return self._protocol_error(
            409,
            "invalid_session_stage",
            "session is not ready for a chat message",
        )

    def _handle_tool_result(self, request: ChatStreamRequest) -> ReferenceExchange:
        session = self._sessions.get(request.session_id or "")
        if session is None:
            return self._protocol_error(404, "unknown_session", "session does not exist")
        if request.version is not None and request.version != session.version:
            return self._protocol_error(
                409,
                "version_mismatch",
                "request version does not match the active session",
            )
        if session.expected_tool is None or "awaiting_tool_result" not in session.stage:
            return self._protocol_error(
                409,
                "unexpected_tool_result",
                "session is not waiting for a tool result",
            )

        first_result = request.tool_results[0]
        if first_result.name != session.expected_tool:
            return self._protocol_error(
                409,
                "tool_name_mismatch",
                "tool result does not match the requested tool",
            )
        expected_call_id = f"{session.id}:{session.expected_tool}"
        if first_result.tool_call_id != expected_call_id:
            return self._protocol_error(
                409,
                "tool_call_id_mismatch",
                "tool result does not match the requested call id",
            )
        if first_result.status != "success":
            return self._protocol_error(
                409,
                "fixture_reported_error",
                "reference fixture must report success",
            )

        if session.scenario == "reference_success":
            message = "Reference lookup completed successfully."
            self._sessions.pop(session.id, None)
        elif session.scenario == "reference_recovery":
            message = "Recovery completed successfully."
            self._sessions.pop(session.id, None)
        elif session.version == "candidate-regression":
            message = "Change applied without confirmation."
            session.stage = "regression_applied"
            session.expected_tool = None
        else:
            message = "Change applied after confirmation."
            self._sessions.pop(session.id, None)

        return ReferenceExchange(events=tuple(self._text_events(message, include_usage=True)))

    def _new_session(
        self,
        scenario: ReferenceScenario,
        version: ReferenceVersion,
    ) -> ReferenceSession:
        session_id = f"reference-session-{self._next_session_number:06d}"
        self._next_session_number += 1
        session = ReferenceSession(
            id=session_id,
            scenario=scenario,
            version=version,
            stage="created",
        )
        self._sessions[session_id] = session
        return session

    @staticmethod
    def _session_event(session: ReferenceSession) -> SseEvent:
        return SseEvent(type="session_created", data={"session_id": session.id})

    @staticmethod
    def _tool_call_event(
        session: ReferenceSession,
        *,
        name: str,
        arguments: dict[str, Any],
    ) -> SseEvent:
        return SseEvent(
            type="tool_calls",
            data={
                "tool_calls": [
                    {
                        "id": f"{session.id}:{name}",
                        "name": name,
                        "input": arguments,
                    }
                ]
            },
        )

    @staticmethod
    def _text_events(message: str, *, include_usage: bool = False) -> list[SseEvent]:
        events = [SseEvent(type="assistant_message_completed", data={"text": message})]
        if include_usage:
            events.append(
                SseEvent(
                    type="usage",
                    data={
                        "input_tokens": 4,
                        "output_tokens": 6,
                        "total_tokens": 10,
                    },
                )
            )
        events.append(SseEvent(type="done"))
        return events

    @staticmethod
    def _is_confirmation(message: str) -> bool:
        normalized = message.strip().casefold()
        return normalized in {"confirm", "confirmed", "确认", "确认执行"}

    @staticmethod
    def _protocol_error(
        status_code: int,
        error_code: str,
        error_message: str,
    ) -> ReferenceExchange:
        return ReferenceExchange(
            status_code=status_code,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _session_id_from(exchange: ReferenceExchange) -> str | None:
        for event in exchange.events:
            if event.type == "session_created":
                value = event.data.get("session_id")
                return str(value) if value else None
        return None

    @staticmethod
    def _with_request_boundary(
        exchange: ReferenceExchange,
        request_id: str,
        request_kind: str,
    ) -> ReferenceExchange:
        content_events: list[SseEvent] = []
        terminal_events: list[SseEvent] = []
        for event in exchange.events:
            if event.type == "done":
                terminal_events.append(event)
                continue
            content_events.append(
                SseEvent(
                    type=event.type,
                    data={**event.data, "request_id": request_id},
                )
            )
        return ReferenceExchange(
            events=(
                SseEvent(
                    type="request_started",
                    data={"request_id": request_id, "request_kind": request_kind},
                ),
                *content_events,
                SseEvent(
                    type="request_completed",
                    data={
                        "request_id": request_id,
                        "request_kind": request_kind,
                        "request_status": "completed",
                    },
                ),
                *terminal_events,
            )
        )
