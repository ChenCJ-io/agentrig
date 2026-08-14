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

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, object]:
        del context, session
        return {
            "source_status": "observed",
            "runtime": {
                "framework": "api-test-driver",
                "framework_version": "1.0.0",
                "protocol": "in-process",
                "protocol_version": "1",
            },
            "features": {
                name: {"status": "observed", "value": value}
                for name, value in self.capabilities().model_dump().items()
            },
        }

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


def test_project_api_keys_are_enforced_by_route_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_SERVER_TOKEN", "deployment-admin-token")
    container = ServiceContainer.build(
        Settings(server={"api_token_ref": "env:AGENTRIG_TEST_SERVER_TOKEN"}),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    admin_headers = {"Authorization": "Bearer deployment-admin-token"}
    with TestClient(create_app(container)) as client:
        reader_issue = client.post(
            "/api/projects/default/api-keys",
            headers=admin_headers,
            json={"name": "read-only", "scopes": ["read"]},
        )
        assert reader_issue.status_code == 201
        reader_headers = {
            "Authorization": f"Bearer {reader_issue.json()['token']}"
        }
        assert (
            client.get(
                "/api/projects/default/production/traces",
                headers=reader_headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/projects/default/review-items",
                headers=reader_headers,
                json={
                    "subject_kind": "case_run",
                    "subject_id": "missing",
                    "created_reason": "must not reach the service",
                    "created_by": "reader",
                },
            ).status_code
            == 401
        )

        reviewer_issue = client.post(
            "/api/projects/default/api-keys",
            headers=admin_headers,
            json={"name": "reviewer", "scopes": ["review"]},
        )
        reviewer_headers = {
            "Authorization": f"Bearer {reviewer_issue.json()['token']}"
        }
        # 404 proves the review-scoped key passed middleware and the request
        # reached subject validation without receiving admin privileges.
        assert (
            client.post(
                "/api/projects/default/review-items",
                headers=reviewer_headers,
                json={
                    "subject_kind": "case_run",
                    "subject_id": "missing",
                    "created_reason": "scope verification",
                    "created_by": "reviewer",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/projects/default/api-keys",
                headers=reviewer_headers,
                json={"name": "forbidden", "scopes": ["admin"]},
            ).status_code
            == 401
        )

        runner_issue = client.post(
            "/api/projects/default/api-keys",
            headers=admin_headers,
            json={"name": "runner", "scopes": ["run"]},
        )
        runner_headers = {
            "Authorization": f"Bearer {runner_issue.json()['token']}"
        }
        # 404 proves the run-scoped key reached durable job validation.
        assert (
            client.post(
                "/api/projects/default/execution-jobs",
                headers=runner_headers,
                json={
                    "run_id": "missing",
                    "case_run_id": "missing",
                    "idempotency_key": "scope-verification",
                },
            ).status_code
            == 404
        )

        ingester_issue = client.post(
            "/api/projects/default/api-keys",
            headers=admin_headers,
            json={"name": "ingest-manager", "scopes": ["ingest"]},
        )
        ingester_headers = {
            "Authorization": f"Bearer {ingester_issue.json()['token']}"
        }
        source = client.post(
            "/api/projects/default/production/ingest-sources",
            headers=ingester_headers,
            json={
                "name": "scope-test-source",
                "allowed_service_names": ["scope-test-agent"],
            },
        )
        assert source.status_code == 201
        assert source.json()["source"]["enabled"] is False
        assert (
            client.post(
                "/api/projects/default/production/ingest-sources",
                headers=reviewer_headers,
                json={
                    "name": "forbidden-source",
                    "allowed_service_names": ["scope-test-agent"],
                },
            ).status_code
            == 401
        )


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
        run_request = {
            "case_ids": ["case_api_v1"],
            "targets": [{"target_id": "target_api_v1", "version": "v1"}],
            "profile_id": "profile_api_v1",
        }
        preview = client.post("/api/runs/preview", json=run_request)
        assert preview.status_code == 200
        assert preview.json()["manifest_schema_version"] == "agentrig.run-manifest.v1"
        assert preview.json()["manifest_hash"].startswith("sha256:")
        assert preview.json()["cell_count"] == 1
        assert preview.json()["attempt_count"] == 1

        submitted = client.post(
            "/api/runs",
            json={
                **run_request,
                "expected_manifest_hash": preview.json()["manifest_hash"],
            },
        )
        assert submitted.status_code == 202
        assert submitted.json()["manifest_hash"] == preview.json()["manifest_hash"]
        assert submitted.json()["cell_count"] == 1
        assert submitted.json()["attempt_count"] == 1
        run_id = submitted.json()["run_id"]
        deadline = time.monotonic() + 2
        run = client.get(f"/api/runs/{run_id}").json()
        while run["status"] not in {"completed", "failed"} and time.monotonic() < deadline:
            time.sleep(0.01)
            run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "completed"
        assert run["manifest_hash"] == preview.json()["manifest_hash"]
        assert run["finished_attempt_count"] == 1
        summary = client.get(f"/api/runs/{run_id}/summary")
        assert summary.status_code == 200
        assert summary.json()["schema_version"] == "agentrig.batch-run-summary.v1"
        assert summary.json()["terminal"] is True
        assert summary.json()["cells_by_status"] == {"completed": 1}
        assert summary.json()["attempts_by_status"] == {"completed": 1}
        assert summary.json()["evaluation_outcomes"] == {"pass": 1}
        case_runs = client.get(f"/api/runs/{run_id}/case-runs").json()["items"]
        detail = client.get(f"/api/case-runs/{case_runs[0]['id']}").json()
        assert detail["evaluation_state"] == "pass"

        cells = client.get(f"/api/runs/{run_id}/cells")
        assert cells.status_code == 200
        assert cells.json()["total"] == 1
        assert cells.json()["items"][0]["cell_key"] == case_runs[0]["cell_key"]
        assert cells.json()["items"][0]["attempt_count"] == 1
        cell_id = cells.json()["items"][0]["cell_key"]
        cell = client.get(f"/api/runs/{run_id}/cells/{cell_id}")
        assert cell.status_code == 200
        assert cell.json()["cell_key"] == cell_id
        assert cell.json()["attempts"][0]["attempt_id"] == case_runs[0]["attempt_id"]
        assert cell.json()["timeline"]
        assert {item["source_type"] for item in cell.json()["timeline"]} == {
            "event",
            "evaluation",
        }

        stale = client.post(
            "/api/runs",
            json={
                **run_request,
                "expected_manifest_hash": "sha256:" + ("0" * 64),
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "plan_stale"

        report = client.get(f"/api/runs/{run_id}/report")
        assert report.status_code == 200
        assert report.json()["schema_version"] == "agentrig.run-report.v1"
        assert report.json()["outcomes"]["pass_count"] == 1
        markdown_report = client.get(
            f"/api/runs/{run_id}/report",
            params={"format": "markdown"},
        )
        assert markdown_report.status_code == 200
        assert "attachment;" in markdown_report.headers["content-disposition"]
        assert "case_api_v1" in markdown_report.text

        quality = client.get(f"/api/runs/{run_id}/quality-report")
        assert quality.status_code == 200
        assert quality.json()["schema_version"] == "agentrig.quality-report.v1"
        assert quality.json()["outcomes"]["pass_count"] == 1
        assert quality.json()["source_snapshot_hash"].startswith("sha256:")
        assert (
            client.get(f"/api/runs/{run_id}/comparison-report").json()["code"]
            == "validation_error"
        )

        export_preview = client.get("/api/targets/target_api_v1/export/preview")
        assert export_preview.status_code == 200
        assert export_preview.json()["counts"] == {
            "runs": 1,
            "test_cases": 1,
            "samples": 0,
            "total_records": 2,
        }
        exported = client.get(
            "/api/targets/target_api_v1/export",
            params={"format": "json"},
        )
        assert exported.status_code == 200
        assert "attachment;" in exported.headers["content-disposition"]
        assert exported.json()["schema_version"] == "agentrig.export.v1"
        assert len(exported.json()["scope"]["runs"]) == 1
        assert (
            client.get(
                "/api/targets/target_api_v1/export",
                params={"format": "xml"},
            ).status_code
            == 422
        )

        assert (
            client.post(
                "/api/targets",
                json={
                    "id": "target_api_baseline",
                    "name": "API Baseline",
                    "driver_type": "api_test",
                    "versions": [{"version": "v1"}],
                },
            ).status_code
            == 201
        )
        ab_submitted = client.post(
            "/api/runs",
            json={
                "case_ids": ["case_api_v1"],
                "targets": [
                    {
                        "role": "baseline",
                        "target_id": "target_api_baseline",
                        "version": "v1",
                    },
                    {
                        "role": "candidate",
                        "target_id": "target_api_v1",
                        "version": "v1",
                    },
                ],
                "profile_id": "profile_api_v1",
            },
        )
        assert ab_submitted.status_code == 202
        ab_run_id = ab_submitted.json()["run_id"]
        ab_deadline = time.monotonic() + 2
        ab_run = client.get(f"/api/runs/{ab_run_id}").json()
        while (
            ab_run["status"] not in {"completed", "failed"}
            and time.monotonic() < ab_deadline
        ):
            time.sleep(0.01)
            ab_run = client.get(f"/api/runs/{ab_run_id}").json()
        assert ab_run["status"] == "completed"

        comparison = client.get(f"/api/runs/{ab_run_id}/comparison-report")
        assert comparison.status_code == 200
        assert comparison.json()["schema_version"] == "agentrig.comparison-report.v1"
        assert comparison.json()["summary"]["unchanged_pass_count"] == 1
        gate = client.post(
            f"/api/runs/{ab_run_id}/release-gate:evaluate",
            json={
                "policy": {
                    "name": "api-test",
                    "minimum_samples": {
                        "comparable_pairs": 1,
                        "latency": 20,
                        "token": 1,
                    },
                }
            },
        )
        assert gate.status_code == 200
        assert gate.json()["schema_version"] == "agentrig.release-gate.v1"
        assert gate.json()["verdict"] == "pass"

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
        assert client.get("/api/test-cases?limit=0").status_code == 422
        assert client.get("/api/test-cases?limit=201").status_code == 422
        assert client.get("/api/test-cases?offset=-1").status_code == 422


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
