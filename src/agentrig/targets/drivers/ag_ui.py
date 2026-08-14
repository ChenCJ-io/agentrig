"""AG-UI HTTP/SSE driver with resumable, ordered runtime event normalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ...identifiers import new_id
from .base import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverSession,
    ToolCall,
    ToolResult,
)


class AgUiDriver:
    """Map the public AG-UI event vocabulary into ``DriverEvent`` v2."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            session_resume=True,
            full_trace=True,
            interrupt=True,
            resume=True,
            external_execution=True,
            nested_agents=True,
            model_call_observation=True,
            ordered_event_cursor=True,
        )

    def validate_configuration(
        self,
        options: dict[str, Any],
        *,
        secret_configured: bool,
    ) -> None:
        del secret_configured
        for name in ("run_path", "health_path", "capability_path"):
            value = options.get(name)
            if value is not None and (not isinstance(value, str) or not value.startswith("/")):
                raise ValueError(f"ag_ui options.{name} must start with '/'")
        headers = options.get("request_headers")
        if headers is not None and not isinstance(headers, dict):
            raise ValueError("ag_ui options.request_headers must be an object")
        limits = {
            "max_reconnects": (0, 10),
            "max_event_bytes": (1_024, 4 * 1_024 * 1_024),
            "max_events": (1, 100_000),
        }
        for name, (minimum, maximum) in limits.items():
            value = options.get(name)
            if value is None:
                continue
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not minimum <= value <= maximum
            ):
                raise ValueError(
                    f"ag_ui options.{name} must be an integer in "
                    f"[{minimum}, {maximum}]"
                )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        endpoint = context.target.get("endpoint")
        if not endpoint:
            raise ValueError("ag_ui target requires endpoint")
        options = dict(context.target.get("options") or {})
        self.validate_configuration(options, secret_configured=context.secret_value is not None)
        headers = {
            str(key): str(value)
            for key, value in dict(options.get("request_headers") or {}).items()
        }
        headers.setdefault("Accept", "text/event-stream")
        if context.secret_value:
            header = str(options.get("auth_header") or "Authorization")
            scheme = str(options.get("auth_scheme") or "Bearer")
            headers[header] = f"{scheme} {context.secret_value}".strip()
        root = str(endpoint).rstrip("/")
        run_path = str(options.get("run_path") or "")
        return DriverSession(
            state={
                "endpoint": f"{root}{run_path}",
                "root_endpoint": root,
                "headers": headers,
                "timeout": context.component_timeout_seconds,
                "thread_id": str(
                    context.initial_state.get("thread_id")
                    or options.get("thread_id")
                    or new_id("thread")
                ),
                "run_id": None,
                "state": dict(context.initial_state.get("state") or {}),
                "messages": [],
                "tools": list(options.get("tools") or []),
                "context": list(options.get("context") or []),
                "forwarded_props": dict(options.get("forwarded_props") or {}),
                "tool_calls": {},
                "text_parts": [],
                "seen_event_ids": set(),
                "last_sequence": -1,
                "last_event_id": None,
                "options": options,
            }
        )

    async def probe(self, context: DriverPrepareContext) -> None:
        session = await self.prepare(context)
        options = session.state["options"]
        health_url = f"{session.state['root_endpoint']}{options.get('health_path', '/health')}"
        client_options = self._client_options(session)
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.get(health_url, headers=session.state["headers"])
            response.raise_for_status()

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, Any]:
        del context
        options = session.state["options"]
        return {
            "source_status": "declared",
            "runtime": {
                "framework": str(options.get("framework") or "ag-ui"),
                "framework_version": options.get("framework_version"),
                "protocol": "ag-ui",
                "protocol_version": str(options.get("protocol_version") or "1"),
            },
            "features": {
                key: {"status": "declared", "value": value}
                for key, value in self.capabilities().model_dump().items()
            },
        }

    def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        message_id = new_id("msg")
        session.state["messages"].append(
            {"id": message_id, "role": "user", "content": message}
        )
        return self._post(session, self._run_input(session))

    def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        for item in results:
            session.state["messages"].append(
                {
                    "id": new_id("msg"),
                    "role": "tool",
                    "toolCallId": item.tool_call_id,
                    "name": item.tool_name,
                    "content": (
                        item.result
                        if isinstance(item.result, str)
                        else json.dumps(item.result, ensure_ascii=False)
                    ),
                }
            )
        return self._post(session, self._run_input(session))

    def resume(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        payload = self._run_input(session)
        payload["forwardedProps"] = {
            **payload["forwardedProps"],
            "agentrig_resume": value,
        }
        return self._post(session, payload)

    def submit_permission_response(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        payload = self._run_input(session)
        payload["forwardedProps"] = {
            **payload["forwardedProps"],
            "agentrig_permission_response": value,
        }
        return self._post(session, payload)

    def submit_external_result(
        self,
        session: DriverSession,
        value: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        payload = self._run_input(session)
        payload["forwardedProps"] = {
            **payload["forwardedProps"],
            "agentrig_external_result": value,
        }
        return self._post(session, payload)

    async def cancel(self, session: DriverSession) -> None:
        session.state["cancelled"] = True
        options = session.state["options"]
        cancel_path = options.get("cancel_path")
        if not cancel_path or not session.state.get("run_id"):
            return
        url = f"{session.state['root_endpoint']}{cancel_path}"
        async with httpx.AsyncClient(**self._client_options(session)) as client:
            await client.post(
                url,
                json={
                    "threadId": session.state["thread_id"],
                    "runId": session.state["run_id"],
                },
                headers=session.state["headers"],
            )

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True

    @staticmethod
    def _run_input(session: DriverSession) -> dict[str, Any]:
        return {
            "threadId": session.state["thread_id"],
            "runId": new_id("aguirun"),
            "state": session.state["state"],
            "messages": session.state["messages"],
            "tools": session.state["tools"],
            "context": session.state["context"],
            "forwardedProps": session.state["forwarded_props"],
        }

    async def _post(
        self,
        session: DriverSession,
        payload: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        options = session.state["options"]
        max_reconnects = int(options.get("max_reconnects", 1))
        max_event_bytes = int(options.get("max_event_bytes", 256 * 1_024))
        max_events = int(options.get("max_events", 10_000))
        reconnects = 0
        event_count = 0
        while True:
            terminal_seen = False
            request_payload = self._resumable_payload(
                session,
                payload,
                reconnecting=reconnects > 0,
            )
            headers = dict(session.state["headers"])
            if session.state.get("last_event_id"):
                headers["Last-Event-ID"] = str(session.state["last_event_id"])
            try:
                async with httpx.AsyncClient(**self._client_options(session)) as client:
                    async with client.stream(
                        "POST",
                        str(session.state["endpoint"]),
                        json=request_payload,
                        headers=headers,
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if len(line.encode("utf-8")) > max_event_bytes:
                                yield DriverEvent(
                                    type=DriverEventType.ERROR,
                                    source="ag-ui",
                                    error="AG-UI event exceeded the configured byte limit",
                                )
                                return
                            if (
                                line.startswith("data:")
                                and line[5:].strip() == "[DONE]"
                            ):
                                terminal_seen = True
                                continue
                            raw = _sse_json(line)
                            if raw is None:
                                continue
                            if str(raw.get("type") or "").upper() in {
                                "RUN_FINISHED",
                                "RUN_ERROR",
                            }:
                                terminal_seen = True
                            event = self._normalize_event(session, raw)
                            if event is None:
                                continue
                            event_count += 1
                            if event_count > max_events:
                                yield DriverEvent(
                                    type=DriverEventType.ERROR,
                                    source="ag-ui",
                                    error="AG-UI stream exceeded the configured event limit",
                                )
                                return
                            yield event
            except httpx.HTTPStatusError as exc:
                if not (
                    exc.response.status_code >= 500
                    and reconnects < max_reconnects
                    and not session.state.get("cancelled")
                ):
                    yield DriverEvent(
                        type=DriverEventType.ERROR,
                        source="ag-ui",
                        error=(
                            "AG-UI endpoint returned HTTP "
                            f"{exc.response.status_code}"
                        ),
                    )
                    return
            except httpx.RequestError as exc:
                if reconnects >= max_reconnects or session.state.get("cancelled"):
                    yield DriverEvent(
                        type=DriverEventType.ERROR,
                        source="ag-ui",
                        error=f"AG-UI request failed: {type(exc).__name__}",
                    )
                    return
            else:
                if terminal_seen:
                    return
                if reconnects >= max_reconnects or session.state.get("cancelled"):
                    yield DriverEvent(
                        type=DriverEventType.ERROR,
                        source="ag-ui",
                        error="AG-UI stream ended before a terminal event",
                    )
                    return
            reconnects += 1

    @staticmethod
    def _resumable_payload(
        session: DriverSession,
        payload: dict[str, Any],
        *,
        reconnecting: bool,
    ) -> dict[str, Any]:
        if not reconnecting:
            return payload
        value = {**payload}
        value["runId"] = session.state.get("run_id") or payload.get("runId")
        value["forwardedProps"] = {
            **dict(payload.get("forwardedProps") or {}),
            "agentrig_cursor": {
                "event_id": session.state.get("last_event_id"),
                "sequence": session.state.get("last_sequence"),
            },
        }
        return value

    def _client_options(self, session: DriverSession) -> dict[str, Any]:
        value: dict[str, Any] = {"timeout": session.state["timeout"]}
        if self._transport is not None:
            value["transport"] = self._transport
        return value

    def _normalize_event(
        self,
        session: DriverSession,
        raw: dict[str, Any],
    ) -> DriverEvent | None:
        raw_type = str(raw.get("type") or "").upper()
        event_id = _optional_string(raw.get("eventId") or raw.get("id"))
        if event_id and event_id in session.state["seen_event_ids"]:
            return None
        sequence = _optional_int(raw.get("sequence") or raw.get("seq"))
        if sequence is not None and sequence <= session.state["last_sequence"]:
            return None
        if event_id:
            session.state["seen_event_ids"].add(event_id)
            session.state["last_event_id"] = event_id
        if sequence is not None:
            session.state["last_sequence"] = sequence
        common: dict[str, Any] = {
            "event_id": event_id,
            "sequence": sequence,
            "parent_event_id": _optional_string(raw.get("parentEventId")),
            "raw_type": raw_type,
            "source": "ag-ui",
            "agent_path": _agent_path(raw),
        }
        if raw_type == "RUN_STARTED":
            run_id = _optional_string(raw.get("runId"))
            thread_id = _optional_string(raw.get("threadId"))
            session.state["run_id"] = run_id
            session.state["thread_id"] = thread_id or session.state["thread_id"]
            session.id = thread_id or run_id
            return DriverEvent(
                type=DriverEventType.SESSION_STARTED,
                session_id=session.id,
                payload=_public_payload(raw),
                **common,
            )
        if raw_type == "RUN_FINISHED":
            return DriverEvent(type=DriverEventType.COMPLETED, payload=_public_payload(raw), **common)
        if raw_type == "RUN_ERROR":
            return DriverEvent(
                type=DriverEventType.ERROR,
                error=str(raw.get("message") or raw.get("error") or "AG-UI run failed"),
                payload=_public_payload(raw),
                **common,
            )
        if raw_type == "TEXT_MESSAGE_CONTENT":
            delta = str(raw.get("delta") or "")
            session.state["text_parts"].append(delta)
            return DriverEvent(
                type=DriverEventType.ASSISTANT_TEXT_DELTA,
                text=delta,
                payload={"message_id": raw.get("messageId")},
                **common,
            )
        if raw_type == "TEXT_MESSAGE_END":
            text = "".join(session.state["text_parts"])
            session.state["text_parts"].clear()
            if text:
                session.state["messages"].append(
                    {
                        "id": str(raw.get("messageId") or new_id("msg")),
                        "role": "assistant",
                        "content": text,
                    }
                )
            return DriverEvent(
                type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
                text=text,
                payload={"message_id": raw.get("messageId")},
                **common,
            )
        if raw_type == "TOOL_CALL_START":
            call_id = str(raw.get("toolCallId") or new_id("toolcall"))
            session.state["tool_calls"][call_id] = {
                "name": str(raw.get("toolCallName") or raw.get("name") or ""),
                "arguments": "",
            }
            return DriverEvent(
                type=DriverEventType.TOOL_CALL_STARTED,
                payload={"tool_call_id": call_id, "tool_name": session.state["tool_calls"][call_id]["name"]},
                **common,
            )
        if raw_type == "TOOL_CALL_ARGS":
            call_id = str(raw.get("toolCallId") or "")
            call = session.state["tool_calls"].setdefault(call_id, {"name": "", "arguments": ""})
            delta = str(raw.get("delta") or "")
            call["arguments"] += delta
            return DriverEvent(
                type=DriverEventType.TOOL_CALL_ARGUMENTS_DELTA,
                payload={"tool_call_id": call_id, "arguments_delta": delta},
                **common,
            )
        if raw_type == "TOOL_CALL_END":
            call_id = str(raw.get("toolCallId") or "")
            call = session.state["tool_calls"].pop(call_id, {"name": "", "arguments": "{}"})
            arguments = _json_object(call.get("arguments"))
            return DriverEvent(
                type=DriverEventType.TOOL_CALLS,
                tool_calls=[ToolCall(id=call_id, name=str(call.get("name") or ""), arguments=arguments)],
                payload={"lifecycle": "completed"},
                **common,
            )
        if raw_type == "TOOL_CALL_RESULT":
            result = raw.get("result", raw.get("content"))
            encoded = json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
            return DriverEvent(
                type=DriverEventType.TOOL_RESULT_OBSERVED,
                payload={
                    "tool_call_id": raw.get("toolCallId"),
                    "tool_name": raw.get("toolCallName") or raw.get("name"),
                    "result_sha256": hashlib.sha256(encoded).hexdigest(),
                    "result_exported": False,
                },
                **common,
            )
        if raw_type in {"USAGE", "USAGE_SNAPSHOT"}:
            return DriverEvent(
                type=DriverEventType.USAGE,
                usage=_usage(raw),
                payload={},
                **common,
            )
        mapping = _AG_UI_EVENT_MAP.get(raw_type)
        if mapping is None:
            return None
        return DriverEvent(type=mapping, payload=_public_payload(raw), **common)


_AG_UI_EVENT_MAP: dict[str, DriverEventType] = {
    "SESSION_STATUS_CHANGED": DriverEventType.SESSION_STATUS_CHANGED,
    "MODEL_CALL_STARTED": DriverEventType.MODEL_CALL_STARTED,
    "MODEL_CALL_COMPLETED": DriverEventType.MODEL_CALL_COMPLETED,
    "DATA_PART": DriverEventType.DATA_PART,
    "TOOL_CALL_COMPLETED": DriverEventType.TOOL_CALL_COMPLETED,
    "PERMISSION_REQUESTED": DriverEventType.PERMISSION_REQUESTED,
    "PERMISSION_RESOLVED": DriverEventType.PERMISSION_RESOLVED,
    "EXTERNAL_EXECUTION_REQUESTED": DriverEventType.EXTERNAL_EXECUTION_REQUESTED,
    "EXTERNAL_EXECUTION_RESOLVED": DriverEventType.EXTERNAL_EXECUTION_RESOLVED,
    "INTERRUPT_REQUESTED": DriverEventType.INTERRUPT_REQUESTED,
    "INTERRUPTED": DriverEventType.INTERRUPTED,
    "RESUMED": DriverEventType.RESUMED,
    "AGENT_STARTED": DriverEventType.AGENT_STARTED,
    "AGENT_COMPLETED": DriverEventType.AGENT_COMPLETED,
    "MEMORY_OPERATION": DriverEventType.MEMORY_OPERATION,
    "WORKSPACE_ARTIFACT": DriverEventType.WORKSPACE_ARTIFACT,
    "STEP_STARTED": DriverEventType.AGENT_STARTED,
    "STEP_FINISHED": DriverEventType.AGENT_COMPLETED,
    "REASONING_START": DriverEventType.THINKING_STARTED,
    "REASONING_MESSAGE_START": DriverEventType.THINKING_STARTED,
    "REASONING_MESSAGE_CONTENT": DriverEventType.THINKING_DELTA,
    "REASONING_MESSAGE_END": DriverEventType.THINKING_COMPLETED,
    "REASONING_END": DriverEventType.THINKING_COMPLETED,
    "STATE_SNAPSHOT": DriverEventType.SESSION_STATUS_CHANGED,
    "STATE_DELTA": DriverEventType.SESSION_STATUS_CHANGED,
    "MESSAGES_SNAPSHOT": DriverEventType.SESSION_STATUS_CHANGED,
    "ACTIVITY_SNAPSHOT": DriverEventType.AGENT_STARTED,
    "ACTIVITY_DELTA": DriverEventType.AGENT_STARTED,
    "CUSTOM": DriverEventType.DATA_PART,
    "RAW": DriverEventType.DATA_PART,
}


def _sse_json(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    value = line[5:].strip()
    if not value or value == "[DONE]":
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return None
    return raw if isinstance(raw, dict) else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {"_invalid_json": True}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _agent_path(raw: dict[str, Any]) -> list[str]:
    value = raw.get("agentPath") or raw.get("activityPath") or []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value else []


def _public_payload(raw: dict[str, Any]) -> dict[str, Any]:
    omitted = {
        "type",
        "delta",
        "content",
        "thinking",
        "reasoning",
        "authorization",
        "cookie",
        "api_key",
        "apikey",
        "secret",
        "token",
        "password",
    }
    return {
        str(key): _public_value(value, omitted)
        for key, value in raw.items()
        if str(key).casefold().replace("-", "_") not in omitted
    }


def _public_value(value: Any, omitted: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_value(item, omitted)
            for key, item in value.items()
            if str(key).casefold().replace("-", "_") not in omitted
        }
    if isinstance(value, list):
        return [_public_value(item, omitted) for item in value]
    return value


def _usage(raw: dict[str, Any]) -> dict[str, Any]:
    raw_usage = raw.get("usage")
    source: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else raw
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens", "inputTokens"),
        "output_tokens": ("output_tokens", "completion_tokens", "outputTokens"),
        "total_tokens": ("total_tokens", "totalTokens"),
        "cached_input_tokens": ("cached_input_tokens", "cachedInputTokens"),
        "reasoning_tokens": ("reasoning_tokens", "reasoningTokens"),
        "model": ("model", "model_id", "modelId"),
        "cost": ("cost",),
        "currency": ("currency",),
        "pricing_snapshot_hash": ("pricing_snapshot_hash", "pricingSnapshotHash"),
    }
    result: dict[str, Any] = {}
    for target, names in aliases.items():
        for name in names:
            value = source.get(name)
            if isinstance(value, (int, float, str)) and not isinstance(value, bool):
                result[target] = value
                break
    return result
