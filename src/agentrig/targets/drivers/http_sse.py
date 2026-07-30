"""通用外置工具循环 HTTP/SSE Driver。

默认协议兼容现有 AgentScope streaming-chat：
POST endpoint，SSE ``data: {type, data}``；工具结果通过同一 endpoint 回灌。
字段名可以在 Target ``options`` 中覆盖，业务特殊协议应实现自定义 Python Driver。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from .base import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverSession,
    ToolCall,
    ToolResult,
)


class HttpSseDriver:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            usage_metrics=True,
            tool_proxy_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        endpoint = context.target.get("endpoint")
        if not endpoint:
            raise ValueError("http_sse target requires endpoint")
        endpoint = str(endpoint).rstrip("/")
        if not endpoint.endswith("/chat/stream"):
            endpoint = f"{endpoint}/chat/stream"
        options = dict(context.target.get("options") or {})
        headers = {
            str(key): str(value)
            for key, value in dict(options.get("request_headers") or {}).items()
        }
        if context.secret_value:
            header = str(options.get("auth_header", "Authorization"))
            scheme = str(options.get("auth_scheme", "Bearer"))
            headers[header] = f"{scheme} {context.secret_value}".strip()
        return DriverSession(
            state={
                "endpoint": endpoint,
                "headers": headers,
                "version": context.version,
                "initial_state": context.initial_state,
                "timeout": context.component_timeout_seconds,
                "session_id": None,
                "tool_proxy": (
                    {
                        "url": context.tool_proxy_url,
                        "headers": context.tool_proxy_headers,
                    }
                    if context.tool_proxy_url
                    else None
                ),
            }
        )

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        payload: dict[str, Any] = {"type": "chat", "message": message}
        self._add_shared_payload(session, payload)
        async for event in self._post(session, payload):
            yield event

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        session_id = session.state.get("session_id")
        if not session_id:
            yield DriverEvent(
                type=DriverEventType.ERROR,
                error="driver did not receive a session id before tool result injection",
            )
            return
        payload: dict[str, Any] = {
            "type": "tool_result",
            "session_id": session_id,
            "tool_results": [
                {
                    "tool_call_id": item.tool_call_id,
                    "name": item.tool_name,
                    "result": (
                        item.result
                        if isinstance(item.result, str)
                        else json.dumps(item.result, ensure_ascii=False)
                    ),
                    "status": "success",
                }
                for item in results
            ],
        }
        self._add_shared_payload(session, payload)
        async for event in self._post(session, payload):
            yield event

    async def cancel(self, session: DriverSession) -> None:
        session.state["cancelled"] = True

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True

    @staticmethod
    def _add_shared_payload(session: DriverSession, payload: dict[str, Any]) -> None:
        if session.state.get("session_id"):
            payload["session_id"] = session.state["session_id"]
        if session.state.get("version") is not None:
            payload["version"] = session.state["version"]
        if session.state.get("initial_state"):
            payload["initial_state"] = session.state["initial_state"]
        if session.state.get("tool_proxy"):
            payload["tool_proxy"] = session.state["tool_proxy"]

    async def _post(
        self,
        session: DriverSession,
        payload: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        client_options: dict[str, Any] = {"timeout": session.state["timeout"]}
        if self._transport is not None:
            client_options["transport"] = self._transport
        async with httpx.AsyncClient(**client_options) as client:
            async with client.stream(
                "POST",
                str(session.state["endpoint"]),
                json=payload,
                headers=session.state["headers"],
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    event = parse_sse_line(line)
                    if event is None:
                        continue
                    if event.type is DriverEventType.SESSION_STARTED and event.session_id:
                        session.id = event.session_id
                        session.state["session_id"] = event.session_id
                    yield event


def parse_sse_line(line: str) -> DriverEvent | None:
    if not line.startswith("data:"):
        return None
    raw_value = line[5:].strip()
    if not raw_value or raw_value == "[DONE]":
        return (
            DriverEvent(type=DriverEventType.COMPLETED)
            if raw_value == "[DONE]"
            else None
        )
    try:
        raw = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    event_type = raw.get("type")
    nested_data = raw.get("data")
    data = (
        cast("dict[str, Any]", nested_data)
        if isinstance(nested_data, dict)
        else cast("dict[str, Any]", raw)
    )
    if event_type in {"session_created", "session_started"}:
        return DriverEvent(
            type=DriverEventType.SESSION_STARTED,
            session_id=data.get("session_id"),
        )
    if event_type in {"text_delta", "assistant_text_delta"}:
        return DriverEvent(
            type=DriverEventType.ASSISTANT_TEXT_DELTA,
            text=str(data.get("text", "")),
        )
    if event_type == "assistant_message_completed":
        return DriverEvent(
            type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            text=str(data.get("text", "")),
            refusal=bool(data.get("refusal", False)),
        )
    if event_type == "tool_calls":
        return DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[
                ToolCall(
                    id=str(item.get("id") or item.get("tool_call_id") or ""),
                    name=str(item.get("name") or ""),
                    arguments=dict(item.get("input") or item.get("arguments") or {}),
                    result_schema=item.get("result_schema"),
                )
                for item in data.get("tool_calls", [])
            ],
        )
    if event_type == "usage":
        return DriverEvent(type=DriverEventType.USAGE, usage=data)
    if event_type in {"done", "completed"}:
        return DriverEvent(type=DriverEventType.COMPLETED)
    if event_type == "error":
        return DriverEvent(
            type=DriverEventType.ERROR,
            error=str(data.get("message") or data.get("error") or "unknown driver error"),
        )
    return None
