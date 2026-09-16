"""Bounded OTLP parsing (protobuf and JSON) and GenAI semantic-convention normalization.

Besides the official OTel GenAI conventions, the normalizer understands the two
most common community dialects so standard instrumentations can point their
exporters at AgentRig without adapters:

- OpenLLMetry / Traceloop: flattened ``gen_ai.prompt.{i}.*`` messages,
  ``gen_ai.usage.prompt_tokens``, ``llm.request.type``, ``traceloop.span.kind``;
- OpenInference (Phoenix): ``llm.input_messages.{i}.message.*``,
  ``llm.token_count.*``, ``llm.model_name``, ``openinference.span.kind``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from ..canonical import canonical_hash
from ..runs.redactor import Redactor
from .schemas import RedactionPolicy

_SENSITIVE_FRAGMENTS = {
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "apikey",
    "password",
    "thinking",
    "reasoning",
}
_INPUT_KEYS = {
    "gen_ai.prompt",
    "gen_ai.input.messages",
    "input.value",
}
_OUTPUT_KEYS = {
    "gen_ai.completion",
    "gen_ai.output.messages",
    "output.value",
}
# Flattened message dialects: (attribute prefix, role suffix, content suffix).
_INPUT_MESSAGE_PREFIXES = (
    ("gen_ai.prompt.", ".role", ".content"),
    ("llm.input_messages.", ".message.role", ".message.content"),
)
_OUTPUT_MESSAGE_PREFIXES = (
    ("gen_ai.completion.", ".role", ".content"),
    ("llm.output_messages.", ".message.role", ".message.content"),
)
_CONTENT_KEY_PREFIXES = tuple(
    prefix for prefix, _, _ in (*_INPUT_MESSAGE_PREFIXES, *_OUTPUT_MESSAGE_PREFIXES)
)
_ID_FIELDS = {"traceId", "spanId", "parentSpanId"}


def parse_export_request(body: bytes) -> Any:
    request = trace_service_pb2.ExportTraceServiceRequest()
    request.ParseFromString(body)
    return request


def parse_export_request_json(body: bytes) -> Any:
    """Parse the OTLP/JSON encoding.

    The OTLP spec deviates from plain proto3 JSON in one place: trace and span
    ids are hex strings instead of base64. Convert them before handing the
    document to the protobuf JSON parser.
    """

    document = json.loads(body.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("OTLP JSON payload must be an object")
    _hex_ids_to_base64(document)
    request = trace_service_pb2.ExportTraceServiceRequest()
    json_format.ParseDict(document, request, ignore_unknown_fields=True)
    return request


def _hex_ids_to_base64(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _ID_FIELDS and isinstance(item, str) and item:
                try:
                    raw = bytes.fromhex(item)
                except ValueError:
                    continue
                value[key] = base64.b64encode(raw).decode("ascii")
            else:
                _hex_ids_to_base64(item)
    elif isinstance(value, list):
        for item in value:
            _hex_ids_to_base64(item)


def export_response(*, rejected_spans: int, message: str = "") -> bytes:
    return bytes(_export_response(rejected_spans, message).SerializeToString())


def export_response_json(*, rejected_spans: int, message: str = "") -> bytes:
    response = _export_response(rejected_spans, message)
    return str(json_format.MessageToJson(response)).encode("utf-8")


def _export_response(rejected_spans: int, message: str) -> Any:
    response = trace_service_pb2.ExportTraceServiceResponse()
    if rejected_spans:
        response.partial_success.rejected_spans = rejected_spans
        response.partial_success.error_message = message[:1_024]
    return response


def count_spans(request: Any) -> int:
    return sum(
        len(scope_spans.spans)
        for resource_spans in request.resource_spans
        for scope_spans in resource_spans.scope_spans
    )


def normalized_spans(
    request: Any,
    *,
    project_id: str,
    policy: RedactionPolicy,
    redactor: Redactor,
    max_attribute_count: int,
    max_attribute_value_chars: int,
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for resource_spans in request.resource_spans:
        resource_attributes = _attributes(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            scope = {
                "name": str(scope_spans.scope.name or ""),
                "version": str(scope_spans.scope.version or ""),
            }
            for span in scope_spans.spans:
                attributes = {**resource_attributes, **_attributes(span.attributes)}
                values.append(
                    _normalize_span(
                        span,
                        attributes=attributes,
                        scope=scope,
                        project_id=project_id,
                        policy=policy,
                        redactor=redactor,
                        max_attribute_count=max_attribute_count,
                        max_attribute_value_chars=max_attribute_value_chars,
                    )
                )
    return values


def _normalize_span(
    span: Any,
    *,
    attributes: dict[str, Any],
    scope: dict[str, str],
    project_id: str,
    policy: RedactionPolicy,
    redactor: Redactor,
    max_attribute_count: int,
    max_attribute_value_chars: int,
) -> dict[str, Any]:
    safe_attributes, rejected_keys = _safe_attributes(
        attributes,
        policy=policy,
        redactor=redactor,
        max_count=max_attribute_count,
        max_chars=max_attribute_value_chars,
    )
    service_name = str(attributes.get("service.name") or "unknown-service")
    environment = _string_or_none(
        attributes.get("deployment.environment.name")
        or attributes.get("deployment.environment")
    )
    session_value = (
        attributes.get("gen_ai.conversation.id")
        or attributes.get("session.id")
        or attributes.get("gen_ai.session.id")
    )
    status = _status(span)
    operation = _operation(attributes)
    input_preview = _preview(
        attributes,
        _INPUT_KEYS,
        _INPUT_MESSAGE_PREFIXES,
        policy.save_input_preview,
        policy,
    )
    output_preview = _preview(
        attributes,
        _OUTPUT_KEYS,
        _OUTPUT_MESSAGE_PREFIXES,
        policy.save_output_preview,
        policy,
    )
    input_full = _full_content(attributes, _INPUT_KEYS, _INPUT_MESSAGE_PREFIXES, policy)
    output_full = _full_content(attributes, _OUTPUT_KEYS, _OUTPUT_MESSAGE_PREFIXES, policy)
    model_call = _model_call(attributes, operation)
    tool_call = _tool_call(attributes, operation, span_name=str(span.name or ""))
    tool_result = _tool_result(attributes, tool_call, policy)
    if tool_call is not None and policy.save_full_content:
        arguments = _first(
            attributes,
            "gen_ai.tool.call.arguments",
            "tool.parameters",
            "input.value",
        )
        if isinstance(arguments, str) and arguments:
            tool_call = {
                **tool_call,
                "arguments_redacted": _redact_preview(arguments)[
                    : policy.full_content_max_chars
                ],
            }
    permission = _permission(attributes, operation)
    memory = _memory_operation(attributes, operation)
    artifact_refs = _artifact_refs(attributes)
    events = [
        {
            "name": str(event.name),
            "occurred_at": _timestamp(event.time_unix_nano).isoformat(),
            "attributes": _safe_attributes(
                _attributes(event.attributes),
                policy=policy,
                redactor=redactor,
                max_count=max_attribute_count,
                max_chars=max_attribute_value_chars,
            )[0],
        }
        for event in span.events
        if not _sensitive_key(str(event.name))
    ]
    release = {
        key: value
        for key, value in {
            "environment": environment,
            "version": attributes.get("service.version"),
            "git_sha": attributes.get("vcs.ref.head.revision"),
            "build_id": attributes.get("service.build.id"),
        }.items()
        if value is not None
    }
    token_usage = {
        key: int(value)
        for key, value in {
            "input_tokens": _first(
                attributes,
                "gen_ai.usage.input_tokens",
                "gen_ai.usage.prompt_tokens",
                "llm.token_count.prompt",
            ),
            "output_tokens": _first(
                attributes,
                "gen_ai.usage.output_tokens",
                "gen_ai.usage.completion_tokens",
                "llm.token_count.completion",
            ),
        }.items()
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }
    normalized: dict[str, Any] = {
        "external_trace_id": bytes(span.trace_id).hex(),
        "external_span_id": bytes(span.span_id).hex(),
        "parent_external_span_id": bytes(span.parent_span_id).hex() or None,
        "name": str(span.name or operation or "unnamed"),
        "span_kind": str(getattr(span, "kind", 0)),
        "started_at": _timestamp(span.start_time_unix_nano),
        "ended_at": _timestamp(span.end_time_unix_nano),
        "status": status,
        "service_name": service_name,
        "environment": environment,
        "release": release or None,
        "external_session_id_hash": (
            _identity_hash(project_id, str(session_value)) if session_value else None
        ),
        "user_identity_hash": (
            _identity_hash(project_id, str(attributes.get("enduser.id")))
            if attributes.get("enduser.id")
            else None
        ),
        "input_preview_redacted": input_preview,
        "output_preview_redacted": output_preview,
        "input_full_redacted": input_full,
        "output_full_redacted": output_full,
        "attributes": {**safe_attributes, "otel.scope": scope},
        "rejected_attribute_keys": rejected_keys,
        "token_usage": token_usage,
        "agent_path": _agent_path(attributes),
        "model_call": model_call,
        "tool_call": tool_call,
        "tool_result": tool_result,
        "permission": permission,
        "memory_operation": memory,
        "artifact_refs": artifact_refs,
        "events": events,
    }
    # Keep ORM values as datetimes while hashing their canonical RFC 3339 form.
    hash_payload = {
        **normalized,
        "started_at": normalized["started_at"].isoformat(),
        "ended_at": normalized["ended_at"].isoformat(),
    }
    normalized["content_hash"] = canonical_hash(hash_payload)
    return normalized


def _attributes(values: Any) -> dict[str, Any]:
    return {str(item.key): _any_value(item.value) for item in values}


def _any_value(value: Any) -> Any:
    selected = value.WhichOneof("value")
    if selected is None:
        return None
    if selected == "array_value":
        return [_any_value(item) for item in value.array_value.values]
    if selected == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    if selected == "bytes_value":
        return f"sha256:{hashlib.sha256(bytes(value.bytes_value)).hexdigest()}"
    return getattr(value, selected)


def _safe_attributes(
    attributes: dict[str, Any],
    *,
    policy: RedactionPolicy,
    redactor: Redactor,
    max_count: int,
    max_chars: int,
) -> tuple[dict[str, Any], list[str]]:
    allowed = set(policy.allowed_attribute_keys)
    accepted: dict[str, Any] = {}
    rejected: list[str] = []
    for key, value in sorted(attributes.items()):
        if len(accepted) >= max_count:
            rejected.append(key)
            continue
        if (
            key not in allowed
            or key in _INPUT_KEYS
            or key in _OUTPUT_KEYS
            or key.startswith(_CONTENT_KEY_PREFIXES)
            or _sensitive_key(key)
        ):
            rejected.append(key)
            continue
        safe_value = redactor.redact({"value": value})["value"]
        if isinstance(safe_value, str):
            safe_value = safe_value[:max_chars]
        elif not isinstance(safe_value, (str, int, float, bool, list, dict)):
            safe_value = None
        accepted[key] = safe_value
    return accepted, rejected


def _preview(
    attributes: dict[str, Any],
    keys: set[str],
    message_prefixes: tuple[tuple[str, str, str], ...],
    enabled: bool,
    policy: RedactionPolicy,
) -> str | None:
    if not enabled:
        return None
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str):
            return _redact_preview(value)[: policy.preview_max_chars]
    assembled = _assemble_messages(attributes, message_prefixes)
    if assembled:
        return _redact_preview(assembled)[: policy.preview_max_chars]
    return None


def _full_content(
    attributes: dict[str, Any],
    keys: set[str],
    message_prefixes: tuple[tuple[str, str, str], ...],
    policy: RedactionPolicy,
) -> str | None:
    """The opt-in full transcript used for case building; still redacted and bounded."""

    if not policy.save_full_content:
        return None
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return _redact_preview(value)[: policy.full_content_max_chars]
    assembled = _assemble_messages(attributes, message_prefixes)
    if assembled:
        return _redact_preview(assembled)[: policy.full_content_max_chars]
    return None


def _tool_result(
    attributes: dict[str, Any],
    tool_call: dict[str, Any] | None,
    policy: RedactionPolicy,
) -> dict[str, Any] | None:
    if tool_call is None or not policy.save_full_content:
        return None
    value = _first(attributes, "gen_ai.tool.call.result", "output.value")
    if not isinstance(value, str) or not value:
        return None
    return {
        "result_redacted": _redact_preview(value)[: policy.full_content_max_chars],
    }


def _assemble_messages(
    attributes: dict[str, Any],
    prefixes: tuple[tuple[str, str, str], ...],
) -> str | None:
    """Rebuild a compact transcript from flattened ``prefix.{i}.suffix`` attributes."""

    for prefix, role_suffix, content_suffix in prefixes:
        lines: list[tuple[int, str]] = []
        for key, value in attributes.items():
            if not key.startswith(prefix) or not key.endswith(content_suffix):
                continue
            index_text = key[len(prefix) : len(key) - len(content_suffix)]
            if not index_text.isdigit():
                continue
            index = int(index_text)
            role = attributes.get(f"{prefix}{index_text}{role_suffix}")
            role_text = str(role) if isinstance(role, str) and role else "message"
            lines.append((index, f"{role_text}: {value}"))
        if lines:
            return "\n".join(text for _, text in sorted(lines))
    return None


def _operation(attributes: dict[str, Any]) -> str:
    explicit = attributes.get("gen_ai.operation.name")
    if isinstance(explicit, str) and explicit:
        return explicit
    request_type = attributes.get("llm.request.type")
    if isinstance(request_type, str) and request_type:
        return {
            "chat": "chat",
            "completion": "text_completion",
            "embedding": "embeddings",
        }.get(request_type, request_type)
    for key in ("openinference.span.kind", "traceloop.span.kind"):
        kind = attributes.get(key)
        if not isinstance(kind, str) or not kind:
            continue
        lowered = kind.casefold()
        if lowered == "llm":
            return "chat"
        if lowered == "embedding":
            return "embeddings"
        if lowered == "tool":
            return "execute_tool"
        if lowered == "agent":
            return "invoke_agent"
    return ""


def _first(attributes: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = attributes.get(key)
        if value is not None:
            return value
    return None


def _model_call(attributes: dict[str, Any], operation: str) -> dict[str, Any] | None:
    model = _first(
        attributes,
        "gen_ai.request.model",
        "gen_ai.response.model",
        "llm.model_name",
    )
    if not model and operation not in {"chat", "text_completion", "embeddings"}:
        return None
    return {
        "operation": operation or None,
        "model": str(model) if model else None,
    }


def _tool_call(
    attributes: dict[str, Any],
    operation: str,
    *,
    span_name: str = "",
) -> dict[str, Any] | None:
    name = attributes.get("gen_ai.tool.name") or attributes.get("tool.name")
    if not name and operation not in {"execute_tool", "tool"}:
        return None
    if not name and span_name:
        name = span_name
    return {
        "tool_name": str(name) if name else None,
        "tool_call_id_hash": (
            hashlib.sha256(str(attributes["gen_ai.tool.call.id"]).encode()).hexdigest()
            if attributes.get("gen_ai.tool.call.id")
            else None
        ),
    }


def _permission(attributes: dict[str, Any], operation: str) -> dict[str, Any] | None:
    decision = attributes.get("agentrig.permission.decision")
    if decision is None and "permission" not in operation:
        return None
    return {"decision": str(decision) if decision is not None else "unknown"}


def _memory_operation(attributes: dict[str, Any], operation: str) -> dict[str, Any] | None:
    if "memory" not in operation:
        return None
    return {
        "operation": operation,
        "namespace_hash": attributes.get("agentrig.memory.namespace_hash"),
    }


def _artifact_refs(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    digest = attributes.get("artifact.digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        return []
    return [
        {
            "digest": digest,
            "media_type": attributes.get("artifact.media_type"),
            "size": attributes.get("artifact.size"),
        }
    ]


def _agent_path(attributes: dict[str, Any]) -> list[str]:
    value = _first(attributes, "gen_ai.agent.id", "gen_ai.agent.name", "agent.name")
    return [str(value)] if value else []


def _status(span: Any) -> str:
    code = int(getattr(span.status, "code", 0))
    return "error" if code == 2 else "ok" if code == 1 else "unset"


def _timestamp(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(max(0, nanoseconds) / 1_000_000_000, tz=timezone.utc)


def _sensitive_key(value: str) -> bool:
    normalized = value.casefold().replace("-", "_")
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def _identity_hash(project_id: str, value: str) -> str:
    return hashlib.sha256(f"{project_id}:{value}".encode("utf-8")).hexdigest()


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None and str(value) else None


def _redact_preview(value: str) -> str:
    value = re.sub(
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "<email>",
        value,
    )
    value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    value = re.sub(
        r"(?i)(authorization|cookie|api[_-]?key|secret|password)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        value,
    )
    return value
