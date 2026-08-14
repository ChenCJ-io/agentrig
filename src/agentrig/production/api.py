"""Standard OTLP/HTTP protobuf receiver outside the AgentRig test API namespace."""

from __future__ import annotations

import gzip
from typing import cast

from fastapi import APIRouter, Request, Response

from ..bootstrap import ServiceContainer
from ..errors import AgentRigError, ErrorCode
from .otlp import export_response

router = APIRouter(tags=["OTLP Production Evidence"])


@router.post("/v1/traces")
async def receive_otlp_traces(request: Request) -> Response:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if content_type not in {"application/x-protobuf", "application/protobuf"}:
        raise AgentRigError(
            ErrorCode.VALIDATION_ERROR,
            "OTLP trace receiver requires application/x-protobuf",
        )
    project_id = request.headers.get("x-agentrig-project", "")
    source_id = request.headers.get("x-agentrig-source", "")
    authorization = request.headers.get("authorization", "")
    if not project_id or not source_id or not authorization.startswith("Bearer "):
        raise AgentRigError(ErrorCode.PERMISSION_DENIED, "OTLP ingest headers are incomplete")
    body = await request.body()
    encoding = request.headers.get("content-encoding", "identity").lower()
    if encoding == "gzip":
        try:
            body = gzip.decompress(body)
        except (gzip.BadGzipFile, EOFError) as exc:
            raise AgentRigError(ErrorCode.VALIDATION_ERROR, "invalid gzip payload") from exc
    elif encoding not in {"", "identity"}:
        raise AgentRigError(ErrorCode.VALIDATION_ERROR, "unsupported OTLP compression")
    services = cast(ServiceContainer, request.app.state.services)
    result = await services.production.ingest_otlp(
        project_id=project_id,
        source_id=source_id,
        token=authorization.removeprefix("Bearer "),
        body=body,
    )
    error_message = "; ".join(result.error_messages)
    return Response(
        content=export_response(
            rejected_spans=result.rejected_spans,
            message=error_message,
        ),
        status_code=200,
        media_type=content_type,
        headers={
            "X-AgentRig-Accepted-Spans": str(result.accepted_spans),
            "X-AgentRig-Duplicate-Spans": str(result.duplicate_spans),
        },
    )
