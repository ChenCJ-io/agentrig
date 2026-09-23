"""Web 直连会话里和 python_agent 对话，再把会话转成回归用例并执行 A/B。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentrig.agents.model_client import ModelOutput
from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.targets.drivers import DriverRegistry

AGENTS_DIR = Path(__file__).parent / "agents"
CURATOR_RESULTS = {
    "lookup_order": {"order_id": "A123", "amount": 88},
    "issue_refund": {"refund_id": "sim_1"},
}


class ToolAwareCurator:
    """按工具名返回模拟结果，代替真实的 OpenAI 兼容模型。"""

    async def generate_json(self, **request: Any) -> ModelOutput:
        tool_name = json.loads(request["messages"][1]["content"])["tool_name"]
        return ModelOutput(
            value={"result": CURATOR_RESULTS[tool_name], "state_updates": {}},
            raw_text="{}",
            metadata={"model": "curator-stub"},
        )


def _last_text(response: Any) -> str:
    assert response.status_code == 200, response.text
    event = response.json()["events"][-1]
    assert event["event_type"] == "assistant_message"
    return str(event["payload"]["text"])


def _wait_for_run(client: TestClient, run_id: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}").json()["status"] in {"completed", "failed"}:
            return
        time.sleep(0.2)
    raise AssertionError(f"run did not finish: {run_id}")


def test_chat_turns_into_a_regression_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_CURATOR_KEY", "test-key")
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=DriverRegistry(subprocess_allowlist=[sys.executable]),
        model_client=ToolAwareCurator(),
    )
    with TestClient(create_app(container)) as client:
        assert client.post(
            "/api/targets",
            json={
                "id": "target_refund",
                "name": "Refund agent",
                "driver_type": "python_agent",
                "options": {
                    "entry": "refund_agent:run",
                    "python": sys.executable,
                    "cwd": str(AGENTS_DIR),
                },
                "versions": [{"version": "baseline"}, {"version": "candidate-regression"}],
            },
        ).status_code == 201
        assert client.post(
            "/api/execution-profiles",
            json={
                "id": "profile_curator",
                "name": "Fixture → Sample → Curator",
                "config": {
                    "provider_chain": [
                        {"name": "fixture"},
                        {"name": "sample"},
                        {"name": "simulation_curator"},
                    ],
                    "curator_model": {
                        "base_url": "https://model.example/v1",
                        "model": "model-name",
                        "secret_ref": "env:AGENTRIG_TEST_CURATOR_KEY",
                    },
                    "primary_evaluator": "rule",
                },
            },
        ).status_code == 201

        # 1. 在直连会话里和基线版本对话，工具结果由 Curator 模拟。
        chat = client.post(
            "/api/v2/target-chats",
            json={
                "target_id": "target_refund",
                "profile_id": "profile_curator",
                "version": "baseline",
            },
        ).json()
        messages = f"/api/v2/target-chats/{chat['id']}/messages"
        first = _last_text(client.post(messages, json={"content": "订单 A123 帮我退款"}))
        assert first == "订单 A123 金额 88，请确认是否退款"
        assert _last_text(client.post(messages, json={"content": "确认"})).startswith("已退款")

        # 2. 一键生成用例草稿：工具调用变成 tool_called 断言，模拟结果变成 Fixture。
        draft = client.post(
            f"/api/v2/target-chats/{chat['id']}/draft-case",
            json={"name": "退款前必须确认"},
        ).json()
        assert draft["review_status"] == "draft"
        assert [turn["user_message"] for turn in draft["turns"]] == ["订单 A123 帮我退款", "确认"]
        assert draft["turns"][0]["fixtures"] == [
            {
                "tool_name": "lookup_order",
                "match_arguments": {"order_id": "A123"},
                "result": CURATOR_RESULTS["lookup_order"],
                "repeatable": False,
            }
        ]
        assert {"kind": "tool_called", "tool_name": "lookup_order"} in [
            {key: value for key, value in item.items() if value is not None}
            for item in draft["turns"][0]["assertions"]
        ]

        # 3. 审核时补上业务规则：第一轮不能直接退款；并让两个版本都执行这条用例。
        turns = draft["turns"]
        turns[0]["assertions"].append({"kind": "tool_not_called", "tool_name": "issue_refund"})
        patched = client.patch(
            f"/api/test-cases/{draft['id']}",
            json={"supported_versions": ["baseline", "candidate-regression"], "turns": turns},
        )
        assert patched.status_code == 200, patched.text

        # 4. A/B 回放：基线通过，跳过确认的候选版本被拦下。
        run = client.post(
            "/api/runs",
            json={
                "case_ids": [draft["id"]],
                "targets": [
                    {"target_id": "target_refund", "version": "baseline", "role": "baseline"},
                    {
                        "target_id": "target_refund",
                        "version": "candidate-regression",
                        "role": "candidate",
                    },
                ],
                "profile_id": "profile_curator",
            },
        )
        assert run.status_code == 202, run.text
        _wait_for_run(client, run.json()["run_id"])
        items = client.get(f"/api/runs/{run.json()['run_id']}/case-runs").json()["items"]
        assert {item["version"]: item["evaluation_state"] for item in items} == {
            "baseline": "pass",
            "candidate-regression": "fail",
        }


def test_observe_only_chat_runs_real_tools_without_hanging() -> None:
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=DriverRegistry(subprocess_allowlist=[sys.executable]),
    )
    with TestClient(create_app(container)) as client:
        assert client.post(
            "/api/targets",
            json={
                "id": "target_refund",
                "name": "Refund agent",
                "driver_type": "python_agent",
                "options": {
                    "entry": "refund_agent:run",
                    "python": sys.executable,
                    "cwd": str(AGENTS_DIR),
                },
            },
        ).status_code == 201
        assert client.post(
            "/api/execution-profiles",
            json={
                "id": "profile_observe",
                "name": "Observe real tools",
                "config": {"tool_mode": "observe_only", "provider_chain": []},
            },
        ).status_code == 201
        chat = client.post(
            "/api/v2/target-chats",
            json={"target_id": "target_refund", "profile_id": "profile_observe"},
        ).json()
        messages = f"/api/v2/target-chats/{chat['id']}/messages"

        assert _last_text(client.post(messages, json={"content": "帮我退款"})) == (
            "订单 A123 金额 199，请确认是否退款"
        )
        assert _last_text(client.post(messages, json={"content": "确认"})) == (
            "已退款：real refund issued for A123 (199)"
        )
