"""OpenAI Chat Completions compatible 被测 Agent Driver。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

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


class OpenAICompatibleDriver:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=False,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            usage_metrics=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        endpoint = context.target.get("endpoint")
        if not endpoint:
            raise ValueError("openai_compatible target requires endpoint")
        url = str(endpoint).rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        options = dict(context.target.get("options") or {})
        messages: list[dict[str, Any]] = []
        if options.get("system_prompt"):
            messages.append({"role": "system", "content": str(options["system_prompt"])})
        if context.initial_state:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "AgentRig initial_state JSON:\n"
                        f"{json.dumps(context.initial_state, ensure_ascii=False)}"
                    ),
                }
            )
        headers = {
            str(key): str(value)
            for key, value in dict(options.get("request_headers") or {}).items()
        }
        if context.secret_value:
            headers.setdefault("Authorization", f"Bearer {context.secret_value}")
        return DriverSession(
            state={
                "endpoint": url,
                "headers": headers,
                "messages": messages,
                "model": options.get("model") or context.version,
                "request_options": dict(options.get("request_options") or {}),
                "timeout": context.component_timeout_seconds,
            }
        )

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        session.state["messages"].append({"role": "user", "content": message})
        async for event in self._complete(session):
            yield event

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        for result in results:
            session.state["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": (
                        result.result
                        if isinstance(result.result, str)
                        else json.dumps(result.result, ensure_ascii=False)
                    ),
                }
            )
        async for event in self._complete(session):
            yield event

    async def cancel(self, session: DriverSession) -> None:
        session.state["cancelled"] = True

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True

    async def _complete(self, session: DriverSession) -> AsyncIterator[DriverEvent]:
        payload = {
            "model": session.state.get("model"),
            "messages": session.state["messages"],
            **session.state["request_options"],
        }
        if payload["model"] is None:
            payload.pop("model")
        client_options: dict[str, Any] = {"timeout": session.state["timeout"]}
        if self._transport is not None:
            client_options["transport"] = self._transport
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                str(session.state["endpoint"]),
                json=payload,
                headers=session.state["headers"],
            )
            response.raise_for_status()
            data = response.json()
        message = data["choices"][0]["message"]
        session.state["messages"].append(message)
        if data.get("usage"):
            usage = dict(data["usage"])
            model = data.get("model") or session.state.get("model")
            if model:
                usage["model"] = str(model)
            yield DriverEvent(type=DriverEventType.USAGE, usage=usage)
        calls = [
            ToolCall(
                id=str(item["id"]),
                name=str(item["function"]["name"]),
                arguments=self._arguments(item["function"].get("arguments")),
            )
            for item in message.get("tool_calls") or []
        ]
        if calls:
            yield DriverEvent(type=DriverEventType.TOOL_CALLS, tool_calls=calls)
            return
        content = message.get("content")
        refusal = message.get("refusal")
        if content or refusal:
            yield DriverEvent(
                type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
                text=str(content or refusal),
                refusal=bool(refusal),
            )
        yield DriverEvent(type=DriverEventType.COMPLETED)

    @staticmethod
    def _arguments(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value or "{}")
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("OpenAI tool call arguments must be a JSON object")
