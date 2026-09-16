"""OpenAI-compatible structured output negotiation."""

from __future__ import annotations

import json

import httpx
import pytest

from agentrig.agents.model_client import OpenAICompatibleModelClient


@pytest.mark.anyio
async def test_model_client_falls_back_from_json_schema_to_json_object() -> None:
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": {"message": "unsupported format"}})
        return httpx.Response(
            200,
            headers={"x-request-id": "request-2"},
            json={
                "model": "compatible-model",
                "choices": [{"message": {"content": '{"kind":"answer"}'}}],
                "usage": {"total_tokens": 7},
            },
        )

    client = OpenAICompatibleModelClient(transport=httpx.MockTransport(handler))
    result = await client.generate_json(
        messages=[{"role": "user", "content": "return json"}],
        json_schema={"type": "object"},
        base_url="https://model.example/v1",
        model="compatible-model",
        api_key="test-key",
        timeout_seconds=5,
        options={},
    )

    assert payloads[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "agentrig_output",
            "strict": True,
            "schema": {"type": "object"},
        },
    }
    assert payloads[1]["response_format"] == {"type": "json_object"}
    assert result.value == {"kind": "answer"}
    assert result.metadata["structured_output_mode"] == "json_object"
    assert result.metadata["structured_output_fallbacks"] == ["http_400:json_schema"]


@pytest.mark.anyio
async def test_model_client_does_not_retry_authentication_failure() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    client = OpenAICompatibleModelClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await client.generate_json(
            messages=[{"role": "user", "content": "return json"}],
            json_schema={"type": "object"},
            base_url="https://model.example/v1",
            model="compatible-model",
            api_key="bad-key",
            timeout_seconds=5,
            options={},
        )

    assert attempts == 1
