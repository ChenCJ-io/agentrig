"""REST API（/api）测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentrig.app import app, create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    # /api 不依赖 MCP/proxy session；种子在 create_app 时已同步预填
    return TestClient(app)


def test_overview_returns_metrics(client: TestClient) -> None:
    r = client.get("/api/overview")
    assert r.status_code == 200
    data = r.json()
    assert "total_cases" in data
    assert "recent_runs" in data
    assert isinstance(data["recent_runs"], list)


def test_cases_list_seeded_and_get(client: TestClient) -> None:
    cases = client.get("/api/cases").json()
    assert isinstance(cases, list)
    assert len(cases) >= 1  # lifespan 种子预填
    first = cases[0]
    one = client.get(f"/api/cases/{first['id']}").json()
    assert one["id"] == first["id"]


def test_get_case_404(client: TestClient) -> None:
    r = client.get("/api/cases/does_not_exist")
    assert r.status_code == 404


def test_upsert_and_run(client: TestClient) -> None:
    case = {
        "id": "tc_api_test",
        "name": "API test",
        "user_message": "hi",
        "expected_tools": [],
        "mock": {},
    }
    put = client.put("/api/cases/tc_api_test", json=case)
    assert put.status_code == 200
    assert put.json()["id"] == "tc_api_test"

    run = client.post("/api/cases/tc_api_test/run").json()
    assert "passed" in run
    assert run["case_id"] == "tc_api_test"


def test_spa_blocks_path_traversal(client: TestClient) -> None:
    """SPA catch-all 不能用 %2e%2e 读 dist 外文件。CI 未 build 前端时跳过。"""
    from pathlib import Path

    if not Path("web/dist").is_dir():
        return
    r = client.get("/%2e%2e/%2e%2e/etc/passwd")
    # resolve 校验后回退 index.html，绝不会返回 /etc/passwd 内容
    assert "root:" not in r.text


def test_token_guard_protects_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """设 AGENTRIG_SERVER__API_TOKEN 后 /api 需 Bearer；空则不保护（默认本地）。"""
    monkeypatch.setenv("AGENTRIG_SERVER__API_TOKEN", "secret")
    fresh = create_app()
    c = TestClient(fresh)
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
