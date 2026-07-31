"""部署时 V1 MCP 只暴露已确认的原子工具。"""

from __future__ import annotations

import json

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from mcp.server.fastmcp.exceptions import ToolError

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.cases.models import ReviewStatus
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.mcp_server import create_mcp_server

EXPECTED_TOOLS = {
    "ping",
    "list_tags",
    "list_test_cases",
    "get_test_case",
    "find_cases_by_tool",
    "get_test_case_schema",
    "create_test_case",
    "update_test_case",
    "delete_test_case",
    "check_target",
    "get_run_cases_schema",
    "run_cases",
    "get_run",
    "list_case_runs",
    "get_case_run",
    "list_case_run_events",
    "cancel_run",
    "submit_external_verdict",
    "list_targets",
    "list_driver_types",
    "get_target_schema",
    "get_target",
    "create_target",
    "update_target",
    "delete_target",
    "list_execution_profiles",
    "get_execution_profile_schema",
    "get_execution_profile",
    "create_execution_profile",
    "update_execution_profile",
    "delete_execution_profile",
    "list_samples",
    "get_sample_schema",
    "get_sample",
    "create_sample",
    "update_sample",
    "delete_sample",
}


def _rpc(request_id: int, method: str, params: dict | None = None) -> dict:
    value: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        value["params"] = params
    return value


def _sse_result(value: str) -> dict:
    for line in reversed(value.splitlines()):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"missing SSE data: {value}")


async def test_v1_mcp_tool_set_and_service_projection() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        server = create_mcp_server(services)
        assert {tool.name for tool in server._tool_manager.list_tools()} == EXPECTED_TOOLS
        assert "approve_test_case" not in EXPECTED_TOOLS
        assert "run_single_case" not in EXPECTED_TOOLS
        drivers = await server._tool_manager.call_tool("list_driver_types", {})
        acp = next(item for item in drivers if item["driver_type"] == "acp")
        assert acp["deployment_ready"] is False
        assert "subprocess_allowlist" not in json.dumps(drivers)
        target_schema = await server._tool_manager.call_tool(
            "get_target_schema",
            {"driver_type": "acp"},
        )
        assert (
            target_schema["options_schema"]["properties"]["command"]["type"]
            == "array"
        )
        assert (
            await server._tool_manager.call_tool(
                "get_execution_profile_schema",
                {},
            )
        )["title"] == "ProfileCreate"
        assert (
            await server._tool_manager.call_tool("get_sample_schema", {})
        )["title"] == "SampleCreate"
        run_schema = await server._tool_manager.call_tool(
            "get_run_cases_schema",
            {},
        )
        assert run_schema["title"] == "RunCasesRequest"
        created = await server._tool_manager.call_tool(
            "create_test_case",
            {
                "value": {
                    "id": "case_mcp_v1",
                    "name": "MCP",
                    "primary_evaluator": "external_controller",
                    "turns": [{"position": 1, "user_message": "hello"}],
                }
            },
        )
        assert created["id"] == "case_mcp_v1"
        listed = await server._tool_manager.call_tool("list_test_cases", {})
        assert listed["items"][0]["id"] == "case_mcp_v1"
    finally:
        await services.close()


async def test_mcp_call_boundary_logs_name_status_duration_and_resource_refs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        server = create_mcp_server(services)
        with caplog.at_level("INFO", logger="agentrig.mcp.audit"):
            await server.call_tool("ping", {})
        assert "tool=ping status=completed duration_ms=" in caplog.text
        assert "refs=-" in caplog.text

        caplog.clear()
        with (
            caplog.at_level("WARNING", logger="agentrig.mcp.audit"),
            pytest.raises(ToolError),
        ):
            await server.call_tool(
                "get_test_case",
                {"case_id": "case_missing_audit"},
            )
        assert "tool=get_test_case status=failed duration_ms=" in caplog.text
        assert "refs=case_missing_audit" in caplog.text
        assert "error=ToolError" in caplog.text
    finally:
        await services.close()


async def test_mcp_business_error_is_structured_and_cannot_approve() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    await services.initialize()
    try:
        server = create_mcp_server(services)
        await server._tool_manager.call_tool(
            "create_test_case",
            {
                "value": {
                    "id": "case_approved",
                    "name": "Approved",
                    "primary_evaluator": "external_controller",
                    "turns": [{"position": 1, "user_message": "hello"}],
                }
            },
        )
        await services.cases.review("case_approved", ReviewStatus.APPROVED)
        with pytest.raises(ToolError) as exc:
            await server._tool_manager.call_tool(
                "delete_test_case",
                {"case_id": "case_approved"},
            )
        detail = json.loads(str(exc.value).split(": ", 1)[1])
        assert detail["code"] == "permission_denied"
    finally:
        await services.close()


async def test_streamable_http_exposes_v1_tools_and_invokes_service() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    app = create_app(services)
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:8000",
            follow_redirects=True,
            headers={"Accept": "application/json, text/event-stream"},
        ) as client:
            initialized = await client.post(
                "/mcp/",
                json=_rpc(
                    1,
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "v1-test", "version": "1"},
                        "capabilities": {},
                    },
                ),
            )
            assert initialized.status_code == 200
            listed = await client.post("/mcp/", json=_rpc(2, "tools/list"))
            names = {
                item["name"]
                for item in _sse_result(listed.text)["result"]["tools"]
            }
            assert names == EXPECTED_TOOLS

            created = await client.post(
                "/mcp/",
                json=_rpc(
                    3,
                    "tools/call",
                    {
                        "name": "create_test_case",
                        "arguments": {
                            "value": {
                                "id": "case_http_mcp",
                                "name": "HTTP MCP",
                                "primary_evaluator": "external_controller",
                                "turns": [
                                    {"position": 1, "user_message": "hello"}
                                ],
                            }
                        },
                    },
                ),
            )
            content = _sse_result(created.text)["result"]["structuredContent"]
            assert content["id"] == "case_http_mcp"
