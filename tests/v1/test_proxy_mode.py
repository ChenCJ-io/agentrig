"""V1 CaseRun 级 Proxy 模式集成测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import uvicorn
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.proxy import BackendRegistry
from agentrig.proxy.scoped import ProxyScopeRegistry
from agentrig.runs.models import CaseRunStatus, RunEventType
from agentrig.runs.schemas import RunCasesRequest
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


class ProxyCallingDriver:
    def __init__(self, scopes: Callable[[], ProxyScopeRegistry]) -> None:
        self._scopes = scopes

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_proxy_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        assert context.tool_proxy_url == "http://proxy.example/mcp"
        token = context.tool_proxy_headers["X-AgentRig-Proxy-Scope"]
        assert context.tool_proxy_headers["Authorization"] == "Bearer server-secret"
        return DriverSession(state={"scope_token": token})

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        scope = self._scopes().get(str(session.state["scope_token"]))
        assert scope is not None
        result = await scope.resolve(
            "business__search",
            {"query": message},
            result_schema={
                "type": "object",
                "required": ["items"],
                "properties": {"items": {"type": "array"}},
            },
        )
        assert result.result == {"items": [{"id": "fixture-hit"}]}
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            text="proxy complete",
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
        session.state["cancelled"] = True

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True


async def test_proxy_mode_uses_case_scoped_provider_chain_and_revokes_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_SERVER_TOKEN", "server-secret")
    database = Database("sqlite+aiosqlite:///:memory:")
    drivers = DriverRegistry()
    services: ServiceContainer | None = None
    drivers.register(
        "proxy_test",
        lambda: ProxyCallingDriver(lambda: _scopes(services)),
    )
    settings = Settings(
        server={"api_token_ref": "env:AGENTRIG_TEST_SERVER_TOKEN"},
        proxy={"public_url": "http://proxy.example/mcp"},
    )
    services = ServiceContainer.build(settings, database=database, drivers=drivers)
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate(
                id="case_proxy",
                name="Proxy case",
                supported_versions=["v1"],
                primary_evaluator="rule",
                turns=[
                    {
                        "position": 1,
                        "user_message": "find it",
                        "fixtures": [
                            {
                                "tool_name": "business__search",
                                "match_arguments": {"query": "find it"},
                                "result": {"items": [{"id": "fixture-hit"}]},
                            }
                        ],
                        "assertions": [
                            {
                                "kind": "tool_called",
                                "tool_name": "business__search",
                            },
                            {"kind": "text_contains", "value": "complete"},
                        ],
                    }
                ],
            )
        )
        await services.targets.create(
            TargetCreate(
                id="target_proxy",
                name="Proxy target",
                driver_type="proxy_test",
                versions=[{"version": "v1"}],
            )
        )
        await services.profiles.create(
            ProfileCreate(
                id="profile_proxy",
                name="Proxy Fixture",
                config={
                    "tool_mode": "proxy",
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            )
        )

        submitted = await services.runs.run_cases(
            RunCasesRequest(
                case_ids=["case_proxy"],
                targets=[{"target_id": "target_proxy"}],
                profile_id="profile_proxy",
            )
        )
        await services.scheduler.wait(submitted.run_id)
        items = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(items.items[0].id)

        assert detail.status is CaseRunStatus.COMPLETED
        assert detail.summary["tool_call_count"] == 1
        assert services.proxy_scopes.active_count() == 0
        proxy_events = [
            event
            for event in detail.events
            if event.event_type
            in {
                RunEventType.TOOL_CALL,
                RunEventType.PROVIDER_ATTEMPT,
                RunEventType.TOOL_RESULT,
            }
        ]
        assert len(proxy_events) == 3
        assert all(event.payload["via"] == "mcp_proxy" for event in proxy_events)
    finally:
        await services.close()


def _scopes(services: ServiceContainer | None) -> ProxyScopeRegistry:
    assert services is not None
    return services.proxy_scopes


@dataclass
class _ToolList:
    tools: list[types.Tool]


class _ProxyBackend:
    async def list_tools(self) -> _ToolList:
        return _ToolList(
            [
                types.Tool(
                    name="search",
                    description="Search",
                    inputSchema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                    outputSchema={
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}},
                    },
                )
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> types.CallToolResult:
        raise AssertionError(f"fixture should intercept real backend call: {name} {arguments}")


class NetworkProxyDriver:
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
                    listed = await mcp.list_tools()
                    assert [tool.name for tool in listed.tools] == ["business__search"]
                    result = await mcp.call_tool(
                        "business__search",
                        {"query": message},
                    )
        assert result.isError is False
        assert result.structuredContent == {"items": [{"id": "network-fixture"}]}
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            text="network proxy complete",
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


async def test_tested_agent_calls_case_scoped_provider_through_real_mcp_http(
    unused_tcp_port: int,
) -> None:
    proxy_url = f"http://127.0.0.1:{unused_tcp_port}/proxy"
    backend_registry = BackendRegistry()
    backend_registry.add("business", _ProxyBackend())
    drivers = DriverRegistry()
    drivers.register("network_proxy", NetworkProxyDriver)
    services = ServiceContainer.build(
        Settings(
            server={"host": "127.0.0.1", "port": unused_tcp_port},
            proxy={"public_url": proxy_url},
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=drivers,
        backend_registry=backend_registry,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(services),
            host="127.0.0.1",
            port=unused_tcp_port,
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_network_proxy",
                    "name": "Network Proxy",
                    "supported_versions": ["v1"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": "hello",
                            "fixtures": [
                                {
                                    "tool_name": "business__search",
                                    "match_arguments": {"query": "hello"},
                                    "result": {
                                        "items": [{"id": "network-fixture"}]
                                    },
                                }
                            ],
                            "assertions": [
                                {
                                    "kind": "tool_called",
                                    "tool_name": "business__search",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_network_proxy",
                    "name": "Network Proxy",
                    "driver_type": "network_proxy",
                    "versions": [{"version": "v1"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_network_proxy",
                    "name": "Network Proxy",
                    "config": {
                        "tool_mode": "proxy",
                        "provider_chain": [{"name": "fixture"}],
                        "primary_evaluator": "rule",
                    },
                }
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest.model_validate(
                {
                    "case_ids": ["case_network_proxy"],
                    "targets": [{"target_id": "target_network_proxy"}],
                    "profile_id": "profile_network_proxy",
                }
            )
        )
        await services.scheduler.wait(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(page.items[0].id)
        assert detail.status is CaseRunStatus.COMPLETED
        assert detail.evaluation_state == "pass"
        assert detail.summary["tool_call_count"] == 1
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
