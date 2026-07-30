"""Demo 3：被测 Agent 经真实 MCP HTTP Proxy 使用 Sample 与 Curator。"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import uvicorn
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from agentrig.agents.model_client import ModelOutput
from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.proxy import BackendRegistry
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolResult,
)
from agentrig.tool_results.models import SampleStatus
from agentrig.tool_results.schemas import SampleCreate

from ._support import execute_one, print_result


class DemoCuratorModel:
    async def generate_json(self, **request: Any) -> ModelOutput:
        del request
        return ModelOutput(
            value={
                "result": {"condition": "sunny", "temperature_c": 26},
                "state_updates": {"weather_generated": True},
            },
            raw_text="{}",
            metadata={"model": "demo-curator"},
        )


@dataclass
class _ToolList:
    tools: list[types.Tool]


class DemoBackend:
    async def list_tools(self) -> _ToolList:
        return _ToolList(
            [
                types.Tool(
                    name="search",
                    description="Search",
                    inputSchema={"type": "object"},
                    outputSchema={
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}},
                    },
                ),
                types.Tool(
                    name="weather",
                    description="Weather",
                    inputSchema={"type": "object"},
                    outputSchema={
                        "type": "object",
                        "required": ["condition", "temperature_c"],
                        "properties": {
                            "condition": {"type": "string"},
                            "temperature_c": {"type": "number"},
                        },
                    },
                ),
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        raise AssertionError(f"Sample/Curator 应截获真实调用: {name} {arguments}")


class McpUsingAgentDriver:
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_proxy_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(
            state={
                "url": context.tool_proxy_url,
                "headers": context.tool_proxy_headers,
            }
        )

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        async with httpx.AsyncClient(headers=session.state["headers"]) as client:
            async with streamable_http_client(
                str(session.state["url"]),
                http_client=client,
            ) as (read, write, _):
                async with ClientSession(read, write) as mcp:
                    await mcp.initialize()
                    search = await mcp.call_tool(
                        "business__search",
                        {"query": message},
                    )
                    weather = await mcp.call_tool(
                        "business__weather",
                        {"city": "Shanghai"},
                    )
        assert search.structuredContent == {"items": [{"title": "approved sample"}]}
        assert weather.structuredContent == {
            "condition": "sunny",
            "temperature_c": 26,
        }
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            text="Sample 与 Curator 均已返回。",
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session, results
        if False:
            yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def run() -> None:
    port = _free_port()
    proxy_url = f"http://127.0.0.1:{port}/proxy"
    backends = BackendRegistry()
    backends.add("business", DemoBackend())
    drivers = DriverRegistry()
    drivers.register("demo_mcp_agent", McpUsingAgentDriver)
    services = ServiceContainer.build(
        Settings(
            server={"host": "127.0.0.1", "port": port},
            proxy={"public_url": proxy_url},
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=drivers,
        model_client=DemoCuratorModel(),
        backend_registry=backends,
    )
    os.environ["AGENTRIG_DEMO_CURATOR_KEY"] = "demo-only"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(services),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    server_task = asyncio.create_task(server.serve())
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        if not server.started:
            raise RuntimeError("Demo proxy server did not start")

        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_mcp_proxy",
                    "name": "MCP Proxy + Sample/Curator",
                    "supported_versions": ["v1"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": "AgentRig",
                            "simulation_instruction": (
                                "为 Shanghai 返回晴天和 26 摄氏度。"
                            ),
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "business__search",
                                },
                                {
                                    "kind": "tool_called",
                                    "tool_name": "business__weather",
                                },
                                {
                                    "kind": "text_contains",
                                    "value": "Sample 与 Curator",
                                },
                            ],
                        }
                    ],
                }
            )
        )
        sample = await services.samples.create(
            SampleCreate.model_validate(
                {
                    "id": "sample_search",
                    "name": "Approved search sample",
                    "tool_name": "business__search",
                    "match_arguments": {"query": "AgentRig"},
                    "content": {"items": [{"title": "approved sample"}]},
                    "supported_versions": ["v1"],
                }
            )
        )
        await services.samples.review(sample.id, SampleStatus.APPROVED)
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_mcp_proxy",
                    "name": "MCP-using Demo Agent",
                    "driver_type": "demo_mcp_agent",
                    "versions": [{"version": "v1"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_mcp_proxy",
                    "name": "Sample then Curator",
                    "config": {
                        "tool_mode": "proxy",
                        "provider_chain": [
                            {"name": "sample"},
                            {"name": "simulation_curator"},
                        ],
                        "primary_evaluator": "rule",
                        "curator_model": {
                            "base_url": "http://curator.test/v1",
                            "model": "demo-curator",
                            "secret_ref": "env:AGENTRIG_DEMO_CURATOR_KEY",
                        },
                    },
                }
            )
        )
        detail = await execute_one(
            services,
            case_id="case_mcp_proxy",
            target_id="target_mcp_proxy",
            profile_id="profile_mcp_proxy",
        )
        assert detail.evaluation_state == "pass"
        sources = [
            event.payload["source"]
            for event in detail.events
            if event.event_type.value == "tool_result"
        ]
        assert sources == ["sample", "simulation_curator"]
        print_result("Demo 3 — MCP Proxy + Sample/Curator", detail)
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)
        os.environ.pop("AGENTRIG_DEMO_CURATOR_KEY", None)


if __name__ == "__main__":
    asyncio.run(run())
