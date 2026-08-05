"""Export a compact, secret-free competition evidence bundle from the local API."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


def get_json(base_url: str, path: str) -> dict[str, Any]:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - operator URL
        return json.load(response)


def pick(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value.get(key) for key in keys if key in value}


def compact_run_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    safe_payload = (
        pick(
            payload,
            "turn_position",
            "phase",
            "status",
            "tool_call_id",
            "tool_call_event_id",
            "tool_name",
            "source",
            "valid",
            "first_action",
            "refusal",
        )
        if isinstance(payload, dict)
        else {}
    )
    return {
        **pick(event, "id", "seq", "event_type", "created_at"),
        "payload": safe_payload,
    }


def compact_evaluation(value: dict[str, Any]) -> dict[str, Any]:
    return pick(
        value,
        "id",
        "evaluator_type",
        "evaluator_source",
        "status",
        "verdict",
        "summary",
        "criteria",
        "evidence_refs",
        "created_at",
        "updated_at",
    )


def build_bundle(base_url: str, session_id: str | None) -> dict[str, Any]:
    health = get_json(base_url, "/api/v2/agentteams/health")
    if session_id is None:
        page = get_json(base_url, "/api/v2/assistant/sessions?limit=1")
        items = page.get("items", [])
        if not items:
            raise RuntimeError("no AssistantSession exists; run the demo first")
        session_id = str(items[0]["id"])

    encoded_session = quote(session_id, safe="")
    session = get_json(base_url, f"/api/v2/assistant/sessions/{encoded_session}")
    events = get_json(
        base_url,
        f"/api/v2/assistant/sessions/{encoded_session}/events?limit=500",
    )
    invocations = get_json(
        base_url,
        f"/api/v2/assistant/sessions/{encoded_session}/agent-invocations?limit=100",
    )
    decisions = get_json(
        base_url,
        f"/api/v2/assistant/sessions/{encoded_session}/decisions?limit=200",
    )
    decision_metrics = get_json(
        base_url,
        f"/api/v2/assistant/sessions/{encoded_session}/decision-metrics",
    )

    plan: dict[str, Any] | None = None
    run: dict[str, Any] | None = None
    case_runs: list[dict[str, Any]] = []
    active_plan_id = session.get("active_plan_id")
    if isinstance(active_plan_id, str):
        plan = get_json(
            base_url,
            f"/api/v2/evaluation-plans/{quote(active_plan_id, safe='')}",
        )
        run_id = plan.get("run_id")
        if isinstance(run_id, str):
            run = get_json(base_url, f"/api/runs/{quote(run_id, safe='')}")
            page = get_json(
                base_url,
                f"/api/runs/{quote(run_id, safe='')}/case-runs?limit=100",
            )
            for summary in page.get("items", []):
                case_run_id = str(summary["id"])
                detail = get_json(
                    base_url,
                    f"/api/case-runs/{quote(case_run_id, safe='')}",
                )
                case_runs.append(
                    {
                        **pick(
                            detail,
                            "id",
                            "run_id",
                            "case_id",
                            "target_id",
                            "status",
                            "evaluation_state",
                            "error_code",
                            "error_message",
                            "summary",
                            "created_at",
                            "started_at",
                            "finished_at",
                        ),
                        "events": [compact_run_event(item) for item in detail.get("events", [])],
                        "evaluations": [
                            compact_evaluation(item) for item in detail.get("evaluations", [])
                        ],
                    }
                )

    return {
        "schema_version": "agentrig.competition-evidence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {"base_url": base_url, "secret_payloads_included": False},
        "agentteams_health": pick(
            health,
            "enabled",
            "configured",
            "matrix_reachable",
            "runtime_reachable",
            "message",
        ),
        "assistant_session": pick(
            session,
            "id",
            "title",
            "status",
            "active_plan_id",
            "last_event_seq",
            "created_at",
            "updated_at",
        ),
        "assistant_event_index": [
            pick(
                item,
                "id",
                "seq",
                "event_type",
                "actor_type",
                "turn_id",
                "plan_id",
                "run_id",
                "case_run_id",
                "invocation_id",
                "matrix_event_id",
                "delivery_status",
                "created_at",
            )
            for item in events.get("items", [])
        ],
        "decision_records": [
            pick(
                item,
                "id",
                "turn_id",
                "parent_decision_id",
                "ordinal",
                "trigger",
                "decision_kind",
                "status",
                "objective",
                "observation_summary",
                "options",
                "selected_action",
                "rationale_summary",
                "evidence_refs",
                "confidence",
                "context_hash",
                "policy_verdict",
                "confirmation_event_id",
                "action_ref_type",
                "action_ref_id",
                "error_code",
                "created_at",
                "authorized_at",
                "started_at",
                "finished_at",
            )
            for item in decisions.get("items", [])
        ],
        "decision_quality_metrics": decision_metrics,
        "plan": plan,
        "agent_invocations": [
            pick(
                item,
                "id",
                "agent_role",
                "status",
                "session_id",
                "plan_id",
                "run_id",
                "case_run_id",
                "tool_call_event_id",
                "input_hash",
                "result_ref",
                "result_hash",
                "matrix_room_id",
                "request_event_id",
                "response_event_id",
                "assigned_agent",
                "deadline",
                "error_code",
                "error_message",
                "retryable",
                "created_at",
                "started_at",
                "finished_at",
            )
            for item in invocations.get("items", [])
        ],
        "run": run,
        "case_runs": case_runs,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--session-id")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".agentrig/local-demo/competition-evidence.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = build_bundle(args.base_url, args.session_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
