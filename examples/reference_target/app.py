"""FastAPI HTTP/SSE application for AgentRig's public reference target."""

import json
from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response, StreamingResponse

from examples.reference_target.scenarios import (
    SCENARIO_CATALOG,
    ReferenceEngine,
    ReferenceExchange,
)
from examples.reference_target.schemas import ChatStreamRequest


def _sse_chunks(exchange: ReferenceExchange) -> Iterator[str]:
    for event in exchange.events:
        if event.type == "done":
            yield "data: [DONE]\n\n"
            continue
        payload = json.dumps(event.as_payload(), separators=(",", ":"))
        yield f"data: {payload}\n\n"


def create_app() -> FastAPI:
    """Create an isolated app and state machine for a demo or test process."""

    engine = ReferenceEngine()
    application = FastAPI(
        title="AgentRig Public Reference Target",
        version="1.0.0",
        description="A deterministic HTTP/SSE target with no model dependency.",
    )
    application.state.reference_engine = engine

    @application.get("/")
    async def describe() -> dict[str, object]:
        return {
            "name": "AgentRig Public Reference Target",
            "protocol": "http_sse",
            "stream_endpoint": "/chat/stream",
            "versions": ["baseline", "candidate-regression"],
            "scenarios": list(SCENARIO_CATALOG),
        }

    @application.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "deterministic": True,
            "active_sessions": engine.active_session_count,
        }

    @application.post("/chat/stream", response_model=None)
    async def chat_stream(request: ChatStreamRequest) -> Response:
        exchange = engine.handle(request)
        if exchange.status_code != 200:
            return JSONResponse(
                status_code=exchange.status_code,
                content={
                    "error": {
                        "code": exchange.error_code,
                        "message": exchange.error_message,
                    }
                },
            )
        return StreamingResponse(
            _sse_chunks(exchange),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_app()
