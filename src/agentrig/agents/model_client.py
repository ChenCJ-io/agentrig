"""两个内置 Agent 共用、可替换的结构化模型客户端。"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    raw_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelClient(Protocol):
    async def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        options: dict[str, Any],
    ) -> ModelOutput: ...


class OpenAICompatibleModelClient:
    """OpenAI-compatible Chat Completions 结构化输出实现。"""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any],
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        options: dict[str, Any],
    ) -> ModelOutput:
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": options.get("temperature", 0),
        }
        if options.get("structured_output", True):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentrig_output",
                    "strict": True,
                    "schema": json_schema,
                },
            }
        passthrough = {
            key: value
            for key, value in options.items()
            if key not in {"temperature", "structured_output"}
        }
        payload.update(passthrough)
        client_options: dict[str, Any] = {"timeout": timeout_seconds}
        if self._transport is not None:
            client_options["transport"] = self._transport
        async with httpx.AsyncClient(**client_options) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        raw_text = content if isinstance(content, str) else json.dumps(content)
        value = self._parse_json(raw_text)
        return ModelOutput(
            value=value,
            raw_text=raw_text,
            metadata={
                "model": data.get("model", model),
                "request_id": response.headers.get("x-request-id"),
                "usage": data.get("usage", {}),
            },
        )

    @staticmethod
    def _parse_json(value: str) -> Any:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines and lines[-1].startswith("```") else lines[1:]
            )
        return json.loads(text)
