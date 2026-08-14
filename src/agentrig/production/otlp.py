"""Bounded OTLP protobuf parsing and GenAI semantic-convention normalization."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

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


def parse_export_request(body: bytes) -> Any:
    request = trace_service_pb2.ExportTraceServiceRequest()
    request.ParseFromString(body)
    return request


def export_response(*, rejected_spans: int, message: str = "") -> bytes:
    response = trace_service_pb2.ExportTraceServiceResponse()
    if rejected_spans:
        response.partial_success.rejected_spans = rejected_spans
        response.partial_success.error_message = message[:1_024]
    return bytes(response.SerializeToString())


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
    operation = str(attributes.get("gen_ai.operation.name") or "")
    input_preview = _preview(
        attributes,
        _INPUT_KEYS,
        policy.save_input_preview,
        policy,
    )
    output_preview = _preview(
        attributes,
        _OUTPUT_KEYS,
        policy.save_output_preview,
        policy,
    )
    model_call = _model_call(attributes, operation)
    tool_call = _tool_call(attributes, operation)
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
            "input_tokens": attributes.get("gen_ai.usage.input_tokens"),
            "output_tokens": attributes.get("gen_ai.usage.output_tokens"),
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
        "attributes": {**safe_attributes, "otel.scope": scope},
        "rejected_attribute_keys": rejected_keys,
        "token_usage": token_usage,
        "agent_path": _agent_path(attributes),
        "model_call": model_call,
        "tool_call": tool_call,
        "tool_result": None,
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
    enabled: bool,
    policy: RedactionPolicy,
) -> str | None:
    if not enabled:
        return None
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str):
            return _redact_preview(value)[: policy.preview_max_chars]
    return None


def _model_call(attributes: dict[str, Any], operation: str) -> dict[str, Any] | None:
    model = attributes.get("gen_ai.request.model") or attributes.get("gen_ai.response.model")
    if not model and operation not in {"chat", "text_completion", "embeddings"}:
        return None
    return {
        "operation": operation or None,
        "model": str(model) if model else None,
    }


def _tool_call(attributes: dict[str, Any], operation: str) -> dict[str, Any] | None:
    name = attributes.get("gen_ai.tool.name") or attributes.get("tool.name")
    if not name and operation not in {"execute_tool", "tool"}:
        return None
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
    value = attributes.get("gen_ai.agent.id") or attributes.get("agent.name")
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
