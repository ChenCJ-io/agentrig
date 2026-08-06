"""Demo 1：HTTP/SSE 被测 Agent + controlled Fixture。"""

from __future__ import annotations

import asyncio
import json

import httpx

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import DriverRegistry, HttpSseDriver

from ._support import execute_one, print_result


async def run() -> None:
    requests: list[dict[str, object]] = []

    def agent_endpoint(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body["type"] == "chat":
            stream = "\n\n".join(
                [
                    'data: {"type":"session_created","data":{"session_id":"demo"}}',
                    (
                        'data: {"type":"tool_calls","data":{"tool_calls":['
                        '{"id":"call_1","name":"search","input":{"query":"AgentRig"}}]}}'
                    ),
                ]
            )
        else:
            stream = "\n\n".join(
                [
                    (
                        'data: {"type":"assistant_message_completed",'
                        '"data":{"text":"找到 1 条结果"}}'
                    ),
                    "data: [DONE]",
                ]
            )
        return httpx.Response(
            200,
            text=f"{stream}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    drivers = DriverRegistry()
    drivers.register(
        "demo_http_sse",
        lambda: HttpSseDriver(transport=httpx.MockTransport(agent_endpoint)),
    )
    services = ServiceContainer.build(
        Settings(target_network={"allowed_hosts": ["demo-agent.test"]}),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=drivers,
    )
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_http_sse",
                    "name": "HTTP/SSE controlled Fixture",
                    "supported_versions": ["v1"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": "AgentRig",
                            "fixtures": [
                                {
                                    "tool_name": "search",
                                    "match_arguments": {"query": "AgentRig"},
                                    "result": {"items": [{"title": "AgentRig V1"}]},
                                }
                            ],
                            "assertions": [
                                {"kind": "tool_called", "tool_name": "search"},
                                {"kind": "text_contains", "value": "1 条结果"},
                            ],
                        }
                    ],
                }
            )
        )
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_http_sse",
                    "name": "HTTP/SSE Demo Agent",
                    "driver_type": "demo_http_sse",
                    "endpoint": "http://demo-agent.test",
                    "versions": [{"version": "v1"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_http_sse",
                    "name": "Controlled Fixture",
                    "config": {
                        "tool_mode": "controlled",
                        "provider_chain": [{"name": "fixture"}],
                        "primary_evaluator": "rule",
                    },
                }
            )
        )
        detail = await execute_one(
            services,
            case_id="case_http_sse",
            target_id="target_http_sse",
            profile_id="profile_http_sse",
        )
        assert detail.evaluation_state == "pass"
        assert [request["type"] for request in requests] == ["chat", "tool_result"]
        print_result("Demo 1 — HTTP/SSE + controlled Fixture", detail)
    finally:
        await services.close()


if __name__ == "__main__":
    asyncio.run(run())
