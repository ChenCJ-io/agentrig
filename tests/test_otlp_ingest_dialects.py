"""OTLP/JSON encoding and community semantic-convention dialects must normalize."""

from __future__ import annotations

import json
from typing import Any

import pytest
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from agentrig.config import ProductionEvidenceConfig
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.infrastructure.database import Database
from agentrig.production import ProductionEvidenceService
from agentrig.production.schemas import IngestSourceCreate, RedactionPolicy
from agentrig.projects import ProjectService
from agentrig.runs.redactor import Redactor

_SERVICE_NAME = "dialect-agent"
_TRACE_HEX = "0a" * 16
_SPAN_HEX = "0b" * 8


async def _service() -> tuple[Database, ProductionEvidenceService, str, str]:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    await ProjectService(database).ensure_default()
    service = ProductionEvidenceService(
        database,
        config=ProductionEvidenceConfig(enabled=True),
        redactor=Redactor(sensitive_keys=["authorization", "secret"], sensitive_paths=[]),
    )
    issue = await service.create_source(
        "default",
        IngestSourceCreate(
            name="dialect-source",
            allowed_service_names=[_SERVICE_NAME],
            enabled=True,
            retention_days=1,
            redaction_policy=RedactionPolicy(
                save_input_preview=True,
                save_output_preview=True,
            ),
        ),
    )
    return database, service, issue.source.id, issue.token


def _attribute(target: Any, key: str, value: Any) -> None:
    item = target.attributes.add()
    item.key = key
    if isinstance(value, bool):
        item.value.bool_value = value
    elif isinstance(value, int):
        item.value.int_value = value
    else:
        item.value.string_value = str(value)


def _protobuf_request(span_attributes: dict[str, Any], *, name: str = "llm call") -> bytes:
    request = trace_service_pb2.ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    _attribute(resource_spans.resource, "service.name", _SERVICE_NAME)
    span = resource_spans.scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex(_TRACE_HEX)
    span.span_id = bytes.fromhex(_SPAN_HEX)
    span.name = name
    span.start_time_unix_nano = 1_704_067_200_000_000_000
    span.end_time_unix_nano = 1_704_067_201_000_000_000
    for key, value in span_attributes.items():
        _attribute(span, key, value)
    return request.SerializeToString()


def _json_request() -> bytes:
    """A spec-shaped OTLP/JSON document: hex ids, string int64s, enum names."""

    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": _SERVICE_NAME},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "manual-json"},
                            "spans": [
                                {
                                    "traceId": _TRACE_HEX,
                                    "spanId": _SPAN_HEX,
                                    "name": "json chat",
                                    "kind": "SPAN_KIND_CLIENT",
                                    "startTimeUnixNano": "1704067200000000000",
                                    "endTimeUnixNano": "1704067201000000000",
                                    "attributes": [
                                        {
                                            "key": "gen_ai.operation.name",
                                            "value": {"stringValue": "chat"},
                                        },
                                        {
                                            "key": "gen_ai.request.model",
                                            "value": {"stringValue": "model-json"},
                                        },
                                        {
                                            "key": "gen_ai.usage.input_tokens",
                                            "value": {"intValue": "21"},
                                        },
                                        {
                                            "key": "gen_ai.input.messages",
                                            "value": {"stringValue": "user: hello json"},
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    ).encode("utf-8")


async def test_otlp_json_encoding_ingests_with_hex_ids_and_string_int64() -> None:
    database, service, source_id, token = await _service()
    try:
        result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=_json_request(),
            payload_format="json",
        )
        assert result.accepted_spans == 1
        page = await service.list_traces("default", limit=10, offset=0)
        trace = page.items[0]
        assert trace.external_trace_id == _TRACE_HEX
        assert trace.token_usage["input_tokens"] == 21
        assert trace.input_preview_redacted == "user: hello json"
        detail = await service.get_trace("default", trace.id)
        model_call = detail.spans[0].model_call
        assert model_call is not None
        assert model_call["model"] == "model-json"
    finally:
        await database.dispose()


async def test_malformed_json_payload_is_rejected() -> None:
    database, service, source_id, token = await _service()
    try:
        with pytest.raises(AgentRigError) as failure:
            await service.ingest_otlp(
                project_id="default",
                source_id=source_id,
                token=token,
                body=b"not json",
                payload_format="json",
            )
        assert failure.value.detail.code is ErrorCode.VALIDATION_ERROR
    finally:
        await database.dispose()


async def test_traceloop_dialect_assembles_messages_tokens_and_model() -> None:
    database, service, source_id, token = await _service()
    try:
        body = _protobuf_request(
            {
                "llm.request.type": "chat",
                "gen_ai.request.model": "model-tl",
                "gen_ai.prompt.0.role": "system",
                "gen_ai.prompt.0.content": "be brief",
                "gen_ai.prompt.1.role": "user",
                "gen_ai.prompt.1.content": "hello traceloop",
                "gen_ai.completion.0.role": "assistant",
                "gen_ai.completion.0.content": "hi there",
                "gen_ai.usage.prompt_tokens": 17,
                "gen_ai.usage.completion_tokens": 5,
                "traceloop.span.kind": "llm",
            }
        )
        result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=body,
        )
        assert result.accepted_spans == 1
        trace = (await service.list_traces("default", limit=10, offset=0)).items[0]
        assert trace.input_preview_redacted == "system: be brief\nuser: hello traceloop"
        assert trace.output_preview_redacted == "assistant: hi there"
        assert trace.token_usage == {"input_tokens": 17, "output_tokens": 5}
        detail = await service.get_trace("default", trace.id)
        assert detail.spans[0].model_call == {"operation": "chat", "model": "model-tl"}
        span_attributes = detail.spans[0].attributes
        assert not any(key.startswith("gen_ai.prompt.") for key in span_attributes)
        assert not any(key.startswith("gen_ai.completion.") for key in span_attributes)
    finally:
        await database.dispose()


async def test_openinference_dialect_maps_llm_and_tool_spans() -> None:
    database, service, source_id, token = await _service()
    try:
        llm_body = _protobuf_request(
            {
                "openinference.span.kind": "LLM",
                "llm.model_name": "model-oi",
                "llm.input_messages.0.message.role": "user",
                "llm.input_messages.0.message.content": "hello openinference",
                "llm.output_messages.0.message.role": "assistant",
                "llm.output_messages.0.message.content": "done",
                "llm.token_count.prompt": 9,
                "llm.token_count.completion": 3,
            }
        )
        result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=llm_body,
        )
        assert result.accepted_spans == 1
        trace = (await service.list_traces("default", limit=10, offset=0)).items[0]
        assert trace.input_preview_redacted == "user: hello openinference"
        assert trace.output_preview_redacted == "assistant: done"
        assert trace.token_usage == {"input_tokens": 9, "output_tokens": 3}
        llm_detail = await service.get_trace("default", trace.id)
        assert llm_detail.spans[0].model_call == {"operation": "chat", "model": "model-oi"}

        tool_request = trace_service_pb2.ExportTraceServiceRequest()
        resource_spans = tool_request.resource_spans.add()
        _attribute(resource_spans.resource, "service.name", _SERVICE_NAME)
        span = resource_spans.scope_spans.add().spans.add()
        span.trace_id = bytes.fromhex("0c" * 16)
        span.span_id = bytes.fromhex("0d" * 8)
        span.name = "search_flights"
        span.start_time_unix_nano = 1_704_067_202_000_000_000
        span.end_time_unix_nano = 1_704_067_203_000_000_000
        _attribute(span, "openinference.span.kind", "TOOL")
        tool_result = await service.ingest_otlp(
            project_id="default",
            source_id=source_id,
            token=token,
            body=tool_request.SerializeToString(),
        )
        assert tool_result.accepted_spans == 1
        page = await service.list_traces("default", limit=10, offset=0)
        tool_trace = next(
            item for item in page.items if item.external_trace_id == "0c" * 16
        )
        detail = await service.get_trace("default", tool_trace.id)
        tool_span = detail.spans[0]
        assert tool_span.tool_call is not None
        assert tool_span.tool_call["tool_name"] == "search_flights"
    finally:
        await database.dispose()
