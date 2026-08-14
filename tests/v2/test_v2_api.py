"""V2 HTTP 基础合同与 AgentTeams 禁用降级。"""

import pytest
from fastapi.testclient import TestClient

from agentrig.agents.model_client import ModelOutput
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
        assert created.json()["created_by"] == "web-user"
        session_id = created.json()["id"]
        decisions = client.get(f"/api/v2/assistant/sessions/{session_id}/decisions")
        assert decisions.status_code == 200
        assert decisions.json()["items"] == []
        health = client.get("/api/v2/agentteams/health")
        assert health.status_code == 200
        assert health.json()["enabled"] is False
        message = client.post(
            f"/api/v2/assistant/sessions/{session_id}/messages",
            json={"client_message_id": "http-1", "content": "evaluate"},
        )
        assert message.status_code == 503
        assert message.json()["code"] == "assistant_provider_unavailable"

        assert client.get("/api/v2/assistant/sessions?limit=0").status_code == 422
        assert client.get("/api/v2/assistant/sessions?limit=201").status_code == 422
        assert client.get("/api/v2/assistant/sessions?offset=-1").status_code == 422


class _AnswerModelClient:
    async def generate_json(self, **_kwargs: object) -> ModelOutput:
        return ModelOutput(
            value={
                "kind": "answer",
                "content": "我是 AgentRig 智能评测助手，可以回答资产问题并按需创建评测计划。",
                "goal": None,
                "selection": None,
            },
            raw_text="{}",
            metadata={"request_id": "model-request-1"},
        )


def test_basic_model_provider_answers_without_agentteams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BASIC_ASSISTANT_TEST_KEY", "test-key")
    settings = Settings(
        assistant={
            "basic_provider": {
                "enabled": True,
                "base_url": "https://model.example/v1",
                "model": "test-model",
                "secret_ref": "env:BASIC_ASSISTANT_TEST_KEY",
            }
        }
    )
    container = ServiceContainer.build(
        settings,
        database=Database("sqlite+aiosqlite:///:memory:"),
        model_client=_AnswerModelClient(),
    )
    with TestClient(create_app(container)) as client:
        health = client.get("/api/v2/assistant/provider-health")
        assert health.status_code == 200
        assert health.json() == {
            "enabled": True,
            "available": True,
            "provider": "openai_compatible",
            "message": "基础智能助手已就绪",
        }
        created = client.post(
            "/api/v2/assistant/sessions",
            json={"title": "基础助手真实模型回答"},
        )
        session_id = created.json()["id"]
        receipt = client.post(
            f"/api/v2/assistant/sessions/{session_id}/messages",
            json={"client_message_id": "basic-1", "content": "你是谁？"},
        )
        assert receipt.status_code == 202

        events = client.get(
            f"/api/v2/assistant/sessions/{session_id}/events"
        ).json()["items"]
        reply = next(item for item in events if item["event_type"] == "assistant_message")
        assert reply["payload"]["source"] == "basic_model_provider"
        assert "AgentRig 智能评测助手" in reply["payload"]["content"]

        turn = client.get(
            f"/api/v2/assistant/turns/{receipt.json()['turn_id']}"
        )
        assert turn.status_code == 200
        assert turn.json()["status"] == "completed"
        assert turn.json()["model_metadata"]["provider"] == "openai_compatible"


class _PlanModelClient:
    async def generate_json(self, **_kwargs: object) -> ModelOutput:
        return ModelOutput(
            value={
                "kind": "create_plan",
                "content": "已按当前 Target 和指定用例生成一个有界评测计划，请核对后确认。",
                "goal": {"objective": "验证确认边界"},
                "selection": {
                    "case_ids": ["case_basic_plan"],
                    "targets": [
                        {
                            "role": "candidate",
                            "target_id": "target_basic_plan",
                            "version": "v1",
                        }
                    ],
                    "profile_id": "profile_basic_plan",
                    "repeat_count": 1,
                    "overrides": {},
                },
            },
            raw_text="{}",
        )


def test_basic_model_provider_creates_bounded_plan_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BASIC_ASSISTANT_PLAN_KEY", "test-key")
    container = ServiceContainer.build(
        Settings(
            assistant={
                "basic_provider": {
                    "enabled": True,
                    "base_url": "https://model.example/v1",
                    "model": "test-model",
                    "secret_ref": "env:BASIC_ASSISTANT_PLAN_KEY",
                }
            },
            target_network={"allow_private_networks": True},
        ),
        database=Database("sqlite+aiosqlite:///:memory:"),
        model_client=_PlanModelClient(),
    )
    with TestClient(create_app(container)) as client:
        assert client.post(
            "/api/test-cases",
            json={
                "id": "case_basic_plan",
                "name": "基础助手计划用例",
                "supported_versions": ["v1"],
                "turns": [
                    {
                        "position": 1,
                        "user_message": "hello",
                        "assertions": [
                            {"kind": "text_contains", "value": "hello"}
                        ],
                    }
                ],
            },
        ).status_code == 201
        assert client.post(
            "/api/targets",
            json={
                "id": "target_basic_plan",
                "name": "基础助手 Target",
                "driver_type": "http_sse",
                "endpoint": "http://127.0.0.1:19999/chat",
                "versions": [{"version": "v1"}],
            },
        ).status_code == 201
        assert client.post(
            "/api/execution-profiles",
            json={
                "id": "profile_basic_plan",
                "name": "基础助手 Profile",
                "config": {
                    "provider_chain": [{"name": "fixture"}],
                    "primary_evaluator": "rule",
                },
            },
        ).status_code == 201
        created = client.post(
            "/api/v2/assistant/sessions",
            json={
                "title": "计划预览",
                "workspace_id": "target_basic_plan",
            },
        )
        session_id = created.json()["id"]
        sent = client.post(
            f"/api/v2/assistant/sessions/{session_id}/messages",
            json={
                "client_message_id": "basic-plan-1",
                "content": "用指定用例验证当前 Agent 的确认边界",
            },
        )
        assert sent.status_code == 202
        turn = client.get(
            f"/api/v2/assistant/turns/{sent.json()['turn_id']}"
        ).json()
        assert turn["status"] == "completed", turn["error_message"]
        session = client.get(
            f"/api/v2/assistant/sessions/{session_id}"
        ).json()
        plan = client.get(
            f"/api/v2/evaluation-plans/{session['active_plan_id']}"
        ).json()
        assert plan["status"] == "draft"
        assert plan["selection"]["targets"][0]["target_id"] == "target_basic_plan"
        assert plan["preview"]["manifest_hash"].startswith("sha256:")
        assert plan["preview"]["planned_case_runs"] == 1


def test_principal_header_is_ignored_unless_explicitly_trusted() -> None:
    default_container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    with TestClient(create_app(default_container)) as client:
        created = client.post(
            "/api/v2/assistant/sessions",
            headers={"X-AgentRig-Principal": "spoofed-user"},
            json={"title": "Untrusted principal"},
        )
        assert created.status_code == 201
        assert created.json()["created_by"] == "web-user"

    trusted_container = ServiceContainer.build(
        Settings(server={"trusted_principal_header": "x-verified-user"}),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    with TestClient(create_app(trusted_container)) as client:
        created = client.post(
            "/api/v2/assistant/sessions",
            headers={"X-Verified-User": "verified-user"},
            json={"title": "Trusted principal"},
        )
        assert created.status_code == 201
        assert created.json()["created_by"] == "verified-user"


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
