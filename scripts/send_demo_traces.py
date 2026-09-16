"""Send two sample GenAI traces to an AgentRig OTLP endpoint over OTLP/JSON.

Standard-library only, so users can verify their ingest source without
installing OpenTelemetry:

    uv run python scripts/send_demo_traces.py \
        --endpoint http://127.0.0.1:8000/v1/traces \
        --project default --source <source_id> --token <ingest_token>
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
from typing import Any
from urllib.request import Request, urlopen


def _attribute(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _span(
    *,
    trace_id: str,
    span_id: str,
    name: str,
    started_ns: int,
    duration_ms: int,
    attributes: list[dict[str, Any]],
    error: bool = False,
) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": "SPAN_KIND_CLIENT",
        "startTimeUnixNano": str(started_ns),
        "endTimeUnixNano": str(started_ns + duration_ms * 1_000_000),
        "attributes": attributes,
    }
    if error:
        span["status"] = {"code": "STATUS_CODE_ERROR", "message": "demo failure"}
    return span


def build_request(service_name: str) -> dict[str, Any]:
    now_ns = time.time_ns()
    ok_trace = secrets.token_hex(16)
    failed_trace = secrets.token_hex(16)
    spans = [
        _span(
            trace_id=ok_trace,
            span_id=secrets.token_hex(8),
            name="chat demo-success",
            started_ns=now_ns,
            duration_ms=850,
            attributes=[
                _attribute("gen_ai.operation.name", "chat"),
                _attribute("gen_ai.request.model", "demo-model"),
                _attribute("gen_ai.usage.input_tokens", 42),
                _attribute("gen_ai.usage.output_tokens", 17),
                _attribute("gen_ai.conversation.id", "demo-session-1"),
                _attribute("gen_ai.input.messages", "user: 帮我总结这份报告"),
                _attribute("gen_ai.output.messages", "assistant: 报告要点如下……"),
            ],
        ),
        _span(
            trace_id=failed_trace,
            span_id=secrets.token_hex(8),
            name="chat demo-failure",
            started_ns=now_ns + 1_000_000,
            duration_ms=1200,
            attributes=[
                _attribute("gen_ai.operation.name", "chat"),
                _attribute("gen_ai.request.model", "demo-model"),
                _attribute("error.type", "rate_limit"),
                _attribute("gen_ai.input.messages", "user: 查询订单状态"),
            ],
            error=True,
        ),
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", service_name),
                        _attribute("deployment.environment.name", "demo"),
                    ]
                },
                "scopeSpans": [
                    {"scope": {"name": "agentrig-demo-sender"}, "spans": spans}
                ],
            }
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/traces")
    parser.add_argument("--project", default="default")
    parser.add_argument("--source", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--service-name", default="demo-agent")
    args = parser.parse_args()

    body = json.dumps(build_request(args.service_name)).encode("utf-8")
    request = Request(
        args.endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {args.token}",
            "X-AgentRig-Project": args.project,
            "X-AgentRig-Source": args.source,
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - operator URL
        accepted = response.headers.get("X-AgentRig-Accepted-Spans", "?")
        duplicates = response.headers.get("X-AgentRig-Duplicate-Spans", "?")
        print(f"status={response.status} accepted_spans={accepted} duplicate_spans={duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
