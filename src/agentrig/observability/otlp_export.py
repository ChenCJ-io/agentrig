"""Export terminal Run metadata through OTLP/HTTP without changing Run semantics."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from ..config import RunOtlpExportConfig
from ..runs.schemas import RunView


class RunOtlpExporter:
    def __init__(
        self,
        config: RunOtlpExportConfig,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._headers = dict(headers or {})
        self._transport = transport

    async def __call__(self, run: RunView) -> None:
        payload = build_run_export_request(
            run,
            service_name=self._config.service_name,
        ).SerializeToString()
        options: dict[str, Any] = {"timeout": self._config.timeout_seconds}
        if self._transport is not None:
            options["transport"] = self._transport
        async with httpx.AsyncClient(**options) as client:
            response = await client.post(
                self._config.endpoint,
                content=payload,
                headers={
                    **self._headers,
                    "Content-Type": "application/x-protobuf",
                },
            )
            response.raise_for_status()


def build_run_export_request(
    run: RunView,
    *,
    service_name: str = "agentrig",
) -> trace_service_pb2.ExportTraceServiceRequest:
    """Create one bounded span containing IDs, counts, status, and no content bodies."""

    request = trace_service_pb2.ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    _attribute(resource_spans.resource, "service.name", service_name)
    _attribute(resource_spans.resource, "telemetry.sdk.language", "python")
    scope_spans = resource_spans.scope_spans.add()
    scope_spans.scope.name = "agentrig.run-export"
    scope_spans.scope.version = "1"
    span = scope_spans.spans.add()
    digest = hashlib.sha256(run.id.encode()).digest()
    span.trace_id = digest[:16]
    span.span_id = digest[16:24]
    span.name = "agentrig.run"
    started = run.started_at or run.created_at
    finished = run.finished_at or started
    span.start_time_unix_nano = _unix_nanos(started)
    span.end_time_unix_nano = max(span.start_time_unix_nano, _unix_nanos(finished))
    span.status.code = 2 if run.status.value == "failed" else 1
    for key, value in {
        "agentrig.run.id": run.id,
        "agentrig.run.status": run.status.value,
        "agentrig.run.case_count": run.total_count,
        "agentrig.run.completed_count": run.completed_count,
        "agentrig.run.failed_count": run.failed_count,
        "agentrig.run.skipped_count": run.skipped_count,
        "agentrig.run.cancelled_count": run.cancelled_count,
        "agentrig.run.error_code": run.error_code or "",
    }.items():
        _attribute(span, key, value)
    return request


def _attribute(target: Any, key: str, value: str | int | bool) -> None:
    item = target.attributes.add()
    item.key = key
    if isinstance(value, bool):
        item.value.bool_value = value
    elif isinstance(value, int):
        item.value.int_value = value
    else:
        item.value.string_value = value


def _unix_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)
