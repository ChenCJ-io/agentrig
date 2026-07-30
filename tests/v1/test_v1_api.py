"""V1 HTTP 入口与 Service 共享同一执行链。"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentrig.app import _mount_spa, create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)


class ApiTestDriver:
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(id=context.case_run_id)

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        del session
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[ToolCall(id="call_api", name="search", arguments={"q": message})],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session, results
        yield DriverEvent(type=DriverEventType.ASSISTANT_TEXT_DELTA, text="done")
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        del session


def test_spa_fallback_is_excluded_from_openapi(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>AgentRig</html>", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/ping")
    async def _ping() -> dict[str, str]:
        return {"status": "ok"}

    _mount_spa(app, tmp_path)

    with TestClient(app) as client:
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert "/api/ping" in schema.json()["paths"]
        assert "/{full_path}" not in schema.json()["paths"]
        assert client.get("/workspace").text == "<html>AgentRig</html>"


def test_http_crud_async_run_and_structured_errors() -> None:
    registry = DriverRegistry()
    registry.register("api_test", ApiTestDriver)
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
    )
    with TestClient(create_app(container)) as client:
        case = client.post(
            "/api/test-cases",
            json={
                "id": "case_api_v1",
                "name": "API V1",
                "supported_versions": ["v1"],
                "primary_evaluator": "rule",
                "turns": [
                    {
                        "position": 1,
                        "user_message": "hello",
                        "fixtures": [
                            {
                                "tool_name": "search",
                                "match_arguments": {"q": "hello"},
                                "result": {"items": []},
                            }
                        ],
                        "assertions": [{"kind": "tool_called", "tool_name": "search"}],
                    }
                ],
            },
        )
        assert case.status_code == 201
        assert case.json()["review_status"] == "draft"
        assert client.get("/api/test-cases/schema").status_code == 200

        assert (
            client.post(
                "/api/targets",
                json={
                    "id": "target_api_v1",
                    "name": "API Driver",
                    "driver_type": "api_test",
                    "versions": [{"version": "v1"}],
                },
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/execution-profiles",
                json={
                    "id": "profile_api_v1",
                    "name": "API profile",
                    "config": {
                        "provider_chain": [{"name": "fixture"}],
                        "primary_evaluator": "rule",
                    },
                },
            ).status_code
            == 201
        )
        submitted = client.post(
            "/api/runs",
            json={
                "case_ids": ["case_api_v1"],
                "targets": [{"target_id": "target_api_v1", "version": "v1"}],
                "profile_id": "profile_api_v1",
            },
        )
        assert submitted.status_code == 202
        run_id = submitted.json()["run_id"]
        deadline = time.monotonic() + 2
        run = client.get(f"/api/runs/{run_id}").json()
        while run["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
            run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed"
        case_runs = client.get(f"/api/runs/{run_id}/case-runs").json()["items"]
        detail = client.get(f"/api/case-runs/{case_runs[0]['id']}").json()
        assert detail["evaluation_state"] == "pass"

        approved = client.post(
            "/api/test-cases/case_api_v1/review",
            params={"review_status": "approved"},
        )
        assert approved.status_code == 200
        forbidden = client.patch(
            "/api/test-cases/case_api_v1",
            json={"description": "cannot edit"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "permission_denied"

        invalid = client.post(
            "/api/runs",
            json={"case_ids": [], "targets": []},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "validation_error"
        assert invalid.json()["details"]["errors"]


def test_api_token_protects_v1_http_and_mcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_SERVER_TOKEN", "secret")
    container = ServiceContainer.build(
        Settings(server={"api_token_ref": "env:AGENTRIG_TEST_SERVER_TOKEN"}),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    with TestClient(create_app(container), base_url="http://localhost:8000") as client:
        assert client.get("/api/test-cases").status_code == 401
        assert (
            client.get(
                "/api/test-cases",
                headers={"Authorization": "Bearer secret"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test", "version": "1"},
                        "capabilities": {},
                    },
                },
            ).status_code
            == 401
        )
