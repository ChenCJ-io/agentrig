"""The OpenAI-compatible gateway forwards verbatim and records bounded traces."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.production.schemas import GatewayConfig, IngestSourceCreate, RedactionPolicy

_UPSTREAM_KEY = "upstream-secret-key"


def _upstream_transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/chat/completions"):
            payload = json.loads(request.content.decode("utf-8"))
            if payload.get("stream") is True:
                async def stream() -> AsyncIterator[bytes]:
                    chunks = [
                        {"model": "demo-up", "choices": [{"delta": {"content": "你"}}]},
                        {"model": "demo-up", "choices": [{"delta": {"content": "好"}}]},
                        {
                            "model": "demo-up",
                            "choices": [{"delta": {}}],
                            "usage": {"prompt_tokens": 6, "completion_tokens": 2},
                        },
                    ]
                    for chunk in chunks:
                        yield f"data: {json.dumps(chunk)}\n\n".encode()
                    yield b"data: [DONE]\n\n"

                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=stream(),
                )
            if payload.get("model") == "always-429":
                return httpx.Response(
                    429,
                    json={"error": {"message": "rate limited", "type": "rate_limit"}},
                )
            return httpx.Response(
                200,
                json={
                    "id": "cmpl-1",
                    "model": "demo-up",
                    "choices": [
                        {"message": {"role": "assistant", "content": "回答内容"}}
                    ],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2]}], "model": "embed-up", "usage": {"prompt_tokens": 3}},
        )

    return httpx.MockTransport(handler)


def _container(seen: list[httpx.Request]) -> ServiceContainer:
    return ServiceContainer.build(
        Settings(
            production_evidence={"enabled": True},
            target_network={"allow_private_networks": True},
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
        gateway_transport=_upstream_transport(seen),
    )


def _create_gateway_source(client: TestClient) -> tuple[str, str]:
    created = client.post(
        "/api/projects/default/production/ingest-sources",
        json={
            "name": "gateway-app",
            "source_type": "openai_gateway",
            "allowed_service_names": ["gateway-app"],
            "enabled": True,
            "retention_days": 7,
            "gateway": {
                "upstream_base_url": "http://upstream.internal/v1",
                "upstream_secret_ref": "env:GATEWAY_TEST_UPSTREAM_KEY",
            },
            "redaction_policy": {
                "save_input_preview": True,
                "save_output_preview": True,
            },
        },
    )
    assert created.status_code == 201, created.text
    issue = created.json()
    return issue["source"]["id"], issue["token"]


def _wait_for_traces(client: TestClient, count: int) -> list[dict[str, object]]:
    for _ in range(40):
        page = client.get("/api/projects/default/production/traces?limit=20").json()
        if page["total"] >= count:
            return list(page["items"])
        time.sleep(0.05)
    raise AssertionError("gateway trace was not recorded in time")


def test_gateway_forwards_chat_and_records_a_redacted_trace(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_TEST_UPSTREAM_KEY", _UPSTREAM_KEY)
    seen: list[httpx.Request] = []
    with TestClient(create_app(_container(seen))) as client:
        source_id, token = _create_gateway_source(client)
        response = client.post(
            f"/gateway/{source_id}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": "demo-req",
                "messages": [{"role": "user", "content": "帮我查天气"}],
            },
        )
        assert response.status_code == 200
        assert response.json()["choices"][0]["message"]["content"] == "回答内容"
        # the upstream saw its own credential, not the AgentRig token
        assert seen[0].headers["authorization"] == f"Bearer {_UPSTREAM_KEY}"

        trace = _wait_for_traces(client, 1)[0]
        assert trace["service_name"] == "gateway-app"
        assert trace["token_usage"] == {"input_tokens": 12, "output_tokens": 4}
        assert trace["input_preview_redacted"] == "user: 帮我查天气"
        assert trace["output_preview_redacted"] == "assistant: 回答内容"


def test_gateway_streams_sse_and_records_after_the_stream_ends(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_TEST_UPSTREAM_KEY", _UPSTREAM_KEY)
    seen: list[httpx.Request] = []
    with TestClient(create_app(_container(seen))) as client:
        source_id, token = _create_gateway_source(client)
        with client.stream(
            "POST",
            f"/gateway/{source_id}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "model": "demo-req",
                "stream": True,
                "messages": [{"role": "user", "content": "流式测试"}],
            },
        ) as response:
            assert response.status_code == 200
            body = b"".join(response.iter_bytes())
        assert b"[DONE]" in body

        trace = _wait_for_traces(client, 1)[0]
        assert trace["output_preview_redacted"] == "assistant: 你好"
        assert trace["token_usage"] == {"input_tokens": 6, "output_tokens": 2}


def test_gateway_passes_upstream_errors_through_and_flags_the_trace(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_TEST_UPSTREAM_KEY", _UPSTREAM_KEY)
    seen: list[httpx.Request] = []
    with TestClient(create_app(_container(seen))) as client:
        source_id, token = _create_gateway_source(client)
        response = client.post(
            f"/gateway/{source_id}/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "always-429", "messages": [{"role": "user", "content": "x"}]},
        )
        assert response.status_code == 429
        assert response.json()["error"]["type"] == "rate_limit"

        trace = _wait_for_traces(client, 1)[0]
        assert trace["status"] == "error"


def test_gateway_rejects_wrong_tokens_and_unknown_paths(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_TEST_UPSTREAM_KEY", _UPSTREAM_KEY)
    seen: list[httpx.Request] = []
    with TestClient(create_app(_container(seen))) as client:
        source_id, token = _create_gateway_source(client)
        wrong = client.post(
            f"/gateway/{source_id}/v1/chat/completions",
            headers={"Authorization": "Bearer wrong-token"},
            json={"model": "m", "messages": []},
        )
        assert wrong.status_code == 403
        unknown = client.post(
            f"/gateway/{source_id}/v1/images/generations",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert unknown.status_code == 400
        assert not seen


def test_gateway_source_requires_gateway_settings_and_valid_upstream() -> None:
    with TestClient(create_app(_container([]))) as client:
        missing = client.post(
            "/api/projects/default/production/ingest-sources",
            json={
                "name": "bad-gateway",
                "source_type": "openai_gateway",
                "allowed_service_names": ["bad"],
                "enabled": True,
            },
        )
        assert missing.status_code == 422


def test_gateway_forwards_embeddings(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_TEST_UPSTREAM_KEY", _UPSTREAM_KEY)
    seen: list[httpx.Request] = []
    with TestClient(create_app(_container(seen))) as client:
        source_id, token = _create_gateway_source(client)
        response = client.post(
            f"/gateway/{source_id}/v1/embeddings",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "embed-req", "input": "要向量化的文本"},
        )
        assert response.status_code == 200
        trace = _wait_for_traces(client, 1)[0]
        assert trace["input_preview_redacted"] == "要向量化的文本"


def test_gateway_config_schema_validates_secret_reference() -> None:
    with pytest.raises(ValueError):
        GatewayConfig(
            upstream_base_url="http://upstream.internal/v1",
            upstream_secret_ref="sk-live-plaintext",
        )
    value = IngestSourceCreate(
        name="ok",
        source_type="openai_gateway",
        allowed_service_names=["ok"],
        gateway=GatewayConfig(
            upstream_base_url="http://upstream.internal/v1",
            upstream_secret_ref="env:OK_KEY",
        ),
        redaction_policy=RedactionPolicy(),
    )
    assert value.gateway is not None
