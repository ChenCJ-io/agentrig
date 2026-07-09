"""OpenAICompatProvider 测试（用 httpx.MockTransport，不发真实请求）。"""
from __future__ import annotations

import json

import httpx

from agentrig.providers.openai_compat import OpenAICompatProvider


async def test_generate_parses_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "PASS ok"}}]}
        )

    provider = OpenAICompatProvider(
        base_url="http://x", api_key="k", model="m",
        transport=httpx.MockTransport(handler),
    )
    out = await provider.generate([{"role": "user", "content": "hi"}])
    assert out == "PASS ok"


async def test_generate_sends_auth_header_and_model() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    provider = OpenAICompatProvider(
        "http://x", "secret", "gpt-x", transport=httpx.MockTransport(handler)
    )
    await provider.generate([{"role": "user", "content": "hi"}], model="override")
    assert captured["auth"] == "Bearer secret"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "override"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


async def test_generate_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = OpenAICompatProvider(
        "http://x", "k", "m", transport=httpx.MockTransport(handler)
    )
    raised = False
    try:
        await provider.generate([{"role": "user", "content": "hi"}])
    except httpx.HTTPStatusError:
        raised = True
    assert raised
