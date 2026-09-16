"""OpenAI-compatible relay that records every forwarded call as a production trace.

The gateway is the zero-code ingest lane: an application changes its
``base_url`` to ``/gateway/{source_id}/v1`` and authenticates with the ingest
source token. Requests are forwarded verbatim to the configured upstream
(streaming included) while a bounded, redacted trace is written through the
same OTLP ingest path as lane B, so quotas, redaction, and dedup apply
uniformly.

Failure semantics are deliberately simple: upstream errors pass through
unchanged, the gateway never retries, and recording failures never break the
forwarded response.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.trace.v1 import trace_pb2

from ..errors import AgentRigError, ErrorCode
from ..infrastructure.secrets import SecretResolver
from .schemas import IngestSourceView
from .service import ProductionEvidenceService

if TYPE_CHECKING:
    from ..bootstrap import ServiceContainer

logger = logging.getLogger("agentrig.production.gateway")

router = APIRouter(tags=["OpenAI-compatible Gateway"])

_FORWARDED_PATHS = {
    "chat/completions": "chat",
    "embeddings": "embeddings",
}
class GatewayService:
    def __init__(
        self,
        production: ProductionEvidenceService,
        *,
        secrets_resolver: SecretResolver,
        timeout_seconds: float = 120.0,
        max_request_bytes: int = 2_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._production = production
        self._secrets = secrets_resolver
        self._timeout = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._transport = transport

    async def forward(
        self,
        *,
        source_id: str,
        token: str,
        suffix: str,
        body: bytes,
    ) -> Response:
        operation = _FORWARDED_PATHS.get(suffix)
        if operation is None:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "the gateway only forwards chat/completions and embeddings",
            )
        if len(body) > self._max_request_bytes:
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "gateway request exceeds byte limit")
        source = await self._production.authenticate_gateway_source(source_id, token)
        gateway = source.gateway
        assert gateway is not None
        upstream_key = self._secrets.resolve(gateway.upstream_secret_ref)
        if not upstream_key:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "the upstream secret environment variable is not set",
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR, "gateway request body must be JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "gateway request body must be an object")

        url = f"{gateway.upstream_base_url.rstrip('/')}/{suffix}"
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
        }
        capture = _Capture(
            operation=operation,
            request_model=_string(payload.get("model")),
            input_text=_input_text(operation, payload),
            started_ns=time.time_ns(),
        )
        client = httpx.AsyncClient(transport=self._transport, timeout=self._timeout)
        if payload.get("stream") is True and operation == "chat":
            return await self._forward_stream(
                client,
                url,
                headers,
                body,
                source=source,
                token=token,
                capture=capture,
            )
        try:
            upstream = await client.post(url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            await client.aclose()
            capture.error_type = type(exc).__name__
            await self._record(source, token, capture)
            raise AgentRigError(
                ErrorCode.TARGET_UNREACHABLE,
                "gateway upstream request failed",
                retryable=True,
            ) from exc
        await client.aclose()
        capture.status_code = upstream.status_code
        if upstream.status_code < 400:
            capture.absorb_response(_maybe_json(upstream.content))
        else:
            capture.error_type = f"http_{upstream.status_code}"
        await self._record(source, token, capture)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    async def _forward_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        body: bytes,
        *,
        source: IngestSourceView,
        token: str,
        capture: _Capture,
    ) -> Response:
        request = client.build_request("POST", url, headers=headers, content=body)
        try:
            upstream = await client.send(request, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            capture.error_type = type(exc).__name__
            await self._record(source, token, capture)
            raise AgentRigError(
                ErrorCode.TARGET_UNREACHABLE,
                "gateway upstream request failed",
                retryable=True,
            ) from exc
        capture.status_code = upstream.status_code
        if upstream.status_code >= 400:
            content = await upstream.aread()
            await upstream.aclose()
            await client.aclose()
            capture.error_type = f"http_{upstream.status_code}"
            await self._record(source, token, capture)
            return Response(
                content=content,
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "application/json"),
            )

        async def relay() -> AsyncIterator[bytes]:
            buffer = b""
            try:
                async for chunk in upstream.aiter_bytes():
                    if capture.first_chunk_ns is None:
                        capture.first_chunk_ns = time.time_ns()
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        capture.absorb_sse_line(line)
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()
                # Recording happens after the last chunk left; never let it
                # break or delay the client-facing stream.
                task = asyncio.create_task(self._record(source, token, capture))
                task.add_done_callback(lambda done: done.exception())

        return StreamingResponse(
            relay(),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "text/event-stream"),
        )

    async def _record(
        self,
        source: IngestSourceView,
        token: str,
        capture: _Capture,
    ) -> None:
        try:
            request_bytes = capture.to_otlp(service_name=_service_name(source))
            await self._production.ingest_otlp(
                project_id=source.project_id,
                source_id=source.id,
                token=token,
                body=request_bytes,
            )
        except Exception:
            logger.exception("failed to record a gateway trace for %s", source.id)


def _service_name(source: IngestSourceView) -> str:
    if source.gateway is not None and source.gateway.service_name:
        return source.gateway.service_name
    if source.allowed_service_names:
        return source.allowed_service_names[0]
    return source.name


class _Capture:
    """Bounded request/response capture that becomes one OTLP span."""

    def __init__(
        self,
        *,
        operation: str,
        request_model: str | None,
        input_text: str | None,
        started_ns: int,
    ) -> None:
        self.operation = operation
        self.request_model = request_model
        self.response_model: str | None = None
        self.input_text = input_text
        self.output_parts: list[str] = []
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.status_code: int | None = None
        self.error_type: str | None = None
        self.started_ns = started_ns
        self.first_chunk_ns: int | None = None

    def absorb_response(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        self.response_model = _string(payload.get("model")) or self.response_model
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.input_tokens = _int(usage.get("prompt_tokens"))
            self.output_tokens = _int(usage.get("completion_tokens"))
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                self.output_parts = [message["content"]]

    def absorb_sse_line(self, line: bytes) -> None:
        text = line.strip()
        if not text.startswith(b"data:"):
            return
        data = text[5:].strip()
        if not data or data == b"[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        self.response_model = _string(payload.get("model")) or self.response_model
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.input_tokens = _int(usage.get("prompt_tokens")) or self.input_tokens
            self.output_tokens = _int(usage.get("completion_tokens")) or self.output_tokens
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                self.output_parts.append(delta["content"])

    def to_otlp(self, *, service_name: str) -> bytes:
        request = trace_service_pb2.ExportTraceServiceRequest()
        resource_spans = request.resource_spans.add()
        _set_attribute(resource_spans.resource, "service.name", service_name)
        scope_spans = resource_spans.scope_spans.add()
        scope_spans.scope.name = "agentrig-gateway"
        span = scope_spans.spans.add()
        span.trace_id = secrets.token_bytes(16)
        span.span_id = secrets.token_bytes(8)
        span.name = f"{self.operation} gateway"
        span.start_time_unix_nano = self.started_ns
        span.end_time_unix_nano = max(self.started_ns + 1, time.time_ns())
        if self.error_type is not None:
            span.status.code = trace_pb2.Status.STATUS_CODE_ERROR
        _set_attribute(span, "gen_ai.operation.name", self.operation)
        if self.request_model:
            _set_attribute(span, "gen_ai.request.model", self.request_model)
        if self.response_model:
            _set_attribute(span, "gen_ai.response.model", self.response_model)
        if self.input_tokens is not None:
            _set_attribute(span, "gen_ai.usage.input_tokens", self.input_tokens)
        if self.output_tokens is not None:
            _set_attribute(span, "gen_ai.usage.output_tokens", self.output_tokens)
        if self.error_type is not None:
            _set_attribute(span, "error.type", self.error_type)
        if self.input_text:
            _set_attribute(span, "gen_ai.input.messages", self.input_text)
        if self.output_parts:
            _set_attribute(
                span,
                "gen_ai.output.messages",
                "assistant: " + "".join(self.output_parts),
            )
        if self.first_chunk_ns is not None:
            event = span.events.add()
            event.name = "first_token"
            event.time_unix_nano = self.first_chunk_ns
        return bytes(request.SerializeToString())


def _input_text(operation: str, payload: dict[str, Any]) -> str | None:
    if operation == "chat":
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return None
        lines: list[str] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = _string(item.get("role")) or "message"
            content = item.get("content")
            if isinstance(content, str):
                lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else None
    value = payload.get("input")
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return "\n".join(cast(list[str], value))
    return None


def _maybe_json(content: bytes) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _set_attribute(target: Any, key: str, value: Any) -> None:
    item = target.attributes.add()
    item.key = key
    if isinstance(value, bool):
        item.value.bool_value = value
    elif isinstance(value, int):
        item.value.int_value = value
    else:
        item.value.string_value = str(value)


@router.post("/gateway/{source_id}/v1/{suffix:path}")
async def forward_gateway_request(
    request: Request,
    source_id: str,
    suffix: str,
) -> Response:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise AgentRigError(
            ErrorCode.PERMISSION_DENIED,
            "the gateway requires the ingest source token as a Bearer credential",
        )
    services = cast("ServiceContainer", request.app.state.services)
    return await services.gateway.forward(
        source_id=source_id,
        token=authorization.removeprefix("Bearer "),
        suffix=suffix,
        body=await request.body(),
    )
