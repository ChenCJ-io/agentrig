"""V2 HTTP 基础合同与 AgentTeams 禁用降级。"""

import pytest
from fastapi.testclient import TestClient

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database


def test_v2_session_health_and_disabled_message_boundary() -> None:
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    with TestClient(create_app(container)) as client:
        created = client.post(
            "/api/v2/assistant/sessions",
            json={"title": "V2 HTTP"},
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        health = client.get("/api/v2/agentteams/health")
        assert health.status_code == 200
        assert health.json()["enabled"] is False
        message = client.post(
            f"/api/v2/assistant/sessions/{session_id}/messages",
            json={"client_message_id": "http-1", "content": "evaluate"},
        )
        assert message.status_code == 503
        assert message.json()["code"] == "agentteams_unavailable"


def test_role_mcp_surfaces_require_distinct_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MANAGER_MCP_TEST_TOKEN", "manager-token")
    monkeypatch.setenv("CURATOR_MCP_TEST_TOKEN", "curator-token")
    monkeypatch.setenv("JUDGE_MCP_TEST_TOKEN", "judge-token")
    settings = Settings(
        agentteams={
            "manager_mcp_token_ref": "env:MANAGER_MCP_TEST_TOKEN",
            "curator_mcp_token_ref": "env:CURATOR_MCP_TEST_TOKEN",
            "judge_mcp_token_ref": "env:JUDGE_MCP_TEST_TOKEN",
        }
    )
    container = ServiceContainer.build(
        settings,
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    with TestClient(create_app(container)) as client:
        assert client.post("/mcp/manager/").status_code == 401
        gateway_path = "/mcp-servers/mcp-agentrig-manager/mcp"
        assert client.post(gateway_path).status_code == 401
        assert (
            client.post(
                "/mcp/manager/",
                headers={"Authorization": "Bearer judge-token"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/mcp/manager/",
                headers={"Authorization": "Bearer manager-token"},
            ).status_code
            != 401
        )
        assert (
            client.post(
                gateway_path,
                headers={"Authorization": "Bearer judge-token"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                gateway_path,
                headers={"Authorization": "Bearer manager-token"},
            ).status_code
            != 401
        )
