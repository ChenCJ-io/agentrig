"""Competition evidence export must retain provenance without deployment secrets."""

from __future__ import annotations

import json

from pytest import MonkeyPatch
from scripts.export_competition_evidence import (
    build_bundle,
    compact_case_run,
    compact_plan,
    compact_run,
)


def test_compact_plan_excludes_prompts_runtime_config_and_submit_controls() -> None:
    plan = compact_plan(
        {
            "id": "plan_1",
            "session_id": "session_1",
            "source_turn_id": "turn_1",
            "revision": 2,
            "status": "submitted",
            "goal": {"intent": "private business prompt"},
            "reasoning_summary": {"summary": "private rationale"},
            "selection": {
                "case_ids": ["case_1"],
                "profile_id": "profile_1",
                "repeat_count": 1,
                "targets": [
                    {
                        "role": "candidate",
                        "target_id": "target_1",
                        "version": "v1",
                        "inline_target": {"endpoint": "https://private.invalid"},
                    }
                ],
            },
            "preview": {
                "resolved_case_ids": ["case_1"],
                "planned_case_runs": 1,
                "primary_evaluators": ["evidence_judge"],
                "providers": ["simulation_curator"],
                "profile_snapshot": {
                    "judge_model": {"secret_ref": "env:PRIVATE_MODEL_KEY"}
                },
                "target_snapshots": [
                    {"endpoint": "https://private.invalid", "options": {"device_id": "private"}}
                ],
                "skipped_items": [
                    {
                        "case_id": "case_2",
                        "target_role": "candidate",
                        "code": "unsupported",
                        "message": "private endpoint failed",
                    }
                ],
            },
            "confirmation": {
                "required": True,
                "reasons": ["private reason"],
                "confirmation_event_id": "event_1",
                "confirmed_by": "private-user",
                "confirmed_at": "2026-08-07T00:00:00Z",
            },
            "selection_hash": "sha256:selection",
            "submit_idempotency_key": "secret-looking-submit-key",
            "run_id": "run_1",
            "created_by": "private-user",
        }
    )

    serialized = json.dumps(plan)
    assert plan["selection"]["targets"] == [
        {"role": "candidate", "target_id": "target_1", "version": "v1"}
    ]
    assert plan["preview"]["skipped_items"] == [
        {"case_id": "case_2", "target_role": "candidate", "code": "unsupported"}
    ]
    assert plan["confirmation"] == {
        "required": True,
        "confirmation_event_id": "event_1",
        "confirmed_at": "2026-08-07T00:00:00Z",
    }
    for excluded in (
        "private business prompt",
        "private rationale",
        "https://private.invalid",
        "env:PRIVATE_MODEL_KEY",
        "private-user",
        "secret-looking-submit-key",
    ):
        assert excluded not in serialized


def test_compact_run_and_case_run_exclude_runtime_and_error_details() -> None:
    run = compact_run(
        {
            "id": "run_1",
            "status": "completed",
            "resolved_case_ids": ["case_1"],
            "target_snapshots": [
                {
                    "id": "target_1",
                    "name": "Reference",
                    "driver_type": "http_sse",
                    "version": "v1",
                    "endpoint": "https://private.invalid",
                    "options": {"device_id": "private-device"},
                }
            ],
            "profile_snapshot": {"curator_model": {"secret_ref": "env:PRIVATE_KEY"}},
            "error_message": "private runtime failure",
            "total_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "cancelled_count": 0,
        }
    )
    case_run = compact_case_run(
        {
            "id": "case_run_1",
            "run_id": "run_1",
            "case_id": "case_1",
            "status": "completed",
            "primary_evaluator": "rule",
            "evaluation_state": "pass",
            "error_message": "private case failure",
            "summary": {
                "turn_count": 2,
                "tool_call_count": 1,
                "private_summary": "private response",
            },
            "events": [],
            "evaluations": [],
        }
    )

    serialized = json.dumps({"run": run, "case_run": case_run})
    assert run["targets"] == [
        {
            "id": "target_1",
            "name": "Reference",
            "driver_type": "http_sse",
            "version": "v1",
        }
    ]
    assert case_run["summary"] == {"turn_count": 2, "tool_call_count": 1}
    for excluded in (
        "https://private.invalid",
        "private-device",
        "env:PRIVATE_KEY",
        "private runtime failure",
        "private case failure",
        "private response",
    ):
        assert excluded not in serialized


def test_build_bundle_uses_compact_plan_and_run(monkeypatch: MonkeyPatch) -> None:
    responses = {
        "/api/v2/agentteams/health": {"enabled": True, "configured": True},
        "/api/v2/assistant/sessions/session_1": {
            "id": "session_1",
            "active_plan_id": "plan_1",
        },
        "/api/v2/assistant/sessions/session_1/events?limit=500": {"items": []},
        "/api/v2/assistant/sessions/session_1/agent-invocations?limit=100": {"items": []},
        "/api/v2/assistant/sessions/session_1/decisions?limit=200": {"items": []},
        "/api/v2/assistant/sessions/session_1/decision-metrics": {},
        "/api/v2/evaluation-plans/plan_1": {
            "id": "plan_1",
            "selection": {},
            "preview": {},
            "submit_idempotency_key": "secret-looking-submit-key",
            "run_id": "run_1",
        },
        "/api/runs/run_1": {
            "id": "run_1",
            "status": "completed",
            "profile_snapshot": {"secret_ref": "env:PRIVATE_KEY"},
            "target_snapshots": [],
        },
        "/api/runs/run_1/case-runs?limit=100": {"items": []},
    }

    def fake_get_json(base_url: str, path: str) -> dict[str, object]:
        assert base_url == "http://example.test"
        return responses[path]

    monkeypatch.setattr(
        "scripts.export_competition_evidence.get_json",
        fake_get_json,
    )
    bundle = build_bundle("http://example.test", "session_1")
    serialized = json.dumps(bundle)

    assert bundle["plan"]["id"] == "plan_1"
    assert bundle["run"]["id"] == "run_1"
    assert "secret-looking-submit-key" not in serialized
    assert "env:PRIVATE_KEY" not in serialized
