from __future__ import annotations

import json

import httpx

from agentrig.targets.agentscope_compat import collect_agentscope_live_compat


async def test_agentscope_live_report_is_versioned_hashed_and_body_free() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/capabilities":
            return httpx.Response(
                200,
                json={
                    "version": "2.0.6",
                    "runtime": {"protocol_version": "1"},
                    "features": {
                        "permission_observation": {
                            "status": "observed",
                            "value": True,
                        }
                    },
                },
            )
        body = "".join(
            f"data: {json.dumps(item)}\n\n"
            for item in [
                {
                    "type": "RUN_STARTED",
                    "eventId": "event-1",
                    "sequence": 1,
                    "threadId": "thread-1",
                    "runId": "run-1",
                    "authorization": "must-not-survive",
                },
                {
                    "type": "REASONING_MESSAGE_CONTENT",
                    "eventId": "event-2",
                    "sequence": 2,
                    "delta": "must-not-survive",
                },
                {
                    "type": "RUN_FINISHED",
                    "eventId": "event-3",
                    "sequence": 3,
                },
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    report = await collect_agentscope_live_compat(
        "https://agentscope.invalid",
        transport=httpx.MockTransport(handler),
    )

    assert report.schema_version == "agentrig.agentscope-live-compat.v1"
    assert report.verdict == "pass"
    assert report.observed_version == "2.0.6"
    assert report.terminal_observed is True
    assert report.result_hash.startswith("sha256:")
    serialized = report.model_dump_json()
    assert "must-not-survive" not in serialized
    assert "agentscope.invalid" not in serialized
