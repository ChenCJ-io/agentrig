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
        base_payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": options.get("temperature", 0),
        }
        passthrough = {
            key: value
            for key, value in options.items()
            if key not in {"temperature", "structured_output"}
        }
        base_payload.update(passthrough)
        output_modes = self._output_modes(options.get("structured_output", True))
        client_options: dict[str, Any] = {"timeout": timeout_seconds}
        if self._transport is not None:
            client_options["transport"] = self._transport
        fallback_reasons: list[str] = []
        async with httpx.AsyncClient(**client_options) as client:
            for index, output_mode in enumerate(output_modes):
                payload = self._payload_for_mode(
                    base_payload,
                    output_mode=output_mode,
                    json_schema=json_schema,
                )
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                has_fallback = index + 1 < len(output_modes)
                if response.status_code in {400, 422} and has_fallback:
                    fallback_reasons.append(f"http_{response.status_code}:{output_mode}")
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                raw_text = content if isinstance(content, str) else json.dumps(content)
                try:
                    value = self._parse_json(raw_text)
                except (json.JSONDecodeError, TypeError):
                    if has_fallback:
                        fallback_reasons.append(f"invalid_json:{output_mode}")
                        continue
                    raise
                return ModelOutput(
                    value=value,
                    raw_text=raw_text,
                    metadata={
                        "model": data.get("model", model),
                        "request_id": response.headers.get("x-request-id"),
                        "usage": data.get("usage", {}),
                        "structured_output_mode": output_mode,
                        "structured_output_fallbacks": fallback_reasons,
                    },
                )
        raise RuntimeError("model output negotiation exhausted without a response")

    @staticmethod
    def _output_modes(value: Any) -> list[str]:
        if value is False:
            return ["prompt_json"]
        if value == "json_object":
            return ["json_object", "prompt_json"]
        return ["json_schema", "json_object", "prompt_json"]

    @staticmethod
    def _payload_for_mode(
        base_payload: dict[str, Any],
        *,
        output_mode: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(base_payload)
        if output_mode == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentrig_output",
                    "strict": True,
                    "schema": json_schema,
                },
            }
        elif output_mode == "json_object":
            payload["response_format"] = {"type": "json_object"}
        else:
            payload["messages"] = [
                *base_payload["messages"],
                {
                    "role": "system",
                    "content": (
                        "Return JSON only. The response must be one JSON object matching this "
                        f"JSON Schema: {json.dumps(json_schema, ensure_ascii=False)}"
                    ),
                },
            ]
        return payload

    @staticmethod
    def _parse_json(value: str) -> Any:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines and lines[-1].startswith("```") else lines[1:]
            )
        return json.loads(text)
