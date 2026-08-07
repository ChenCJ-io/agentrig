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


def compact_plan(value: dict[str, Any]) -> dict[str, Any]:
    """Keep plan provenance while excluding prompts, runtime config, and submit controls."""

    selection = value.get("selection")
    safe_selection: dict[str, Any] = {}
    if isinstance(selection, dict):
        safe_selection = pick(selection, "case_ids", "profile_id", "repeat_count")
        targets = selection.get("targets")
        if isinstance(targets, list):
            safe_selection["targets"] = [
                pick(item, "role", "target_id", "version")
                for item in targets
                if isinstance(item, dict)
            ]

    preview = value.get("preview")
    safe_preview: dict[str, Any] = {}
    if isinstance(preview, dict):
        safe_preview = pick(
            preview,
            "resolved_case_ids",
            "planned_case_runs",
            "primary_evaluators",
            "providers",
        )
        skipped_items = preview.get("skipped_items")
        if isinstance(skipped_items, list):
            safe_preview["skipped_items"] = [
                pick(
                    item,
                    "case_id",
                    "target_role",
                    "version",
                    "repeat_index",
                    "comparison_pair_id",
                    "code",
                )
                for item in skipped_items
                if isinstance(item, dict)
            ]

    confirmation = value.get("confirmation")
    safe_confirmation = (
        pick(
            confirmation,
            "required",
            "confirmation_event_id",
            "confirmed_at",
        )
        if isinstance(confirmation, dict)
        else {}
    )
    return {
        **pick(
            value,
            "id",
            "session_id",
            "source_turn_id",
            "parent_plan_id",
            "origin_decision_id",
            "revision",
            "status",
            "selection_hash",
            "run_id",
            "created_at",
            "updated_at",
            "confirmed_at",
            "submitted_at",
        ),
        "selection": safe_selection,
        "preview": safe_preview,
        "confirmation": safe_confirmation,
    }


def compact_run(value: dict[str, Any]) -> dict[str, Any]:
    """Exclude frozen endpoints, device metadata, model config, and error text."""

    target_snapshots = value.get("target_snapshots")
    targets = (
        [
            pick(item, "id", "name", "driver_type", "version")
            for item in target_snapshots
            if isinstance(item, dict)
        ]
        if isinstance(target_snapshots, list)
        else []
    )
    return {
        **pick(
            value,
            "id",
            "status",
            "resolved_case_ids",
            "total_count",
            "completed_count",
            "failed_count",
            "skipped_count",
            "cancelled_count",
            "created_at",
            "started_at",
            "finished_at",
            "error_code",
        ),
        "targets": targets,
    }


def compact_case_run(value: dict[str, Any]) -> dict[str, Any]:
    summary = value.get("summary")
    return {
        **pick(
            value,
            "id",
            "run_id",
            "case_id",
            "version",
            "repeat_index",
            "comparison_pair_id",
            "comparison_role",
            "status",
            "primary_evaluator",
            "evaluation_state",
            "error_code",
            "created_at",
            "started_at",
            "finished_at",
        ),
        "summary": (
            pick(summary, "turn_count", "tool_call_count")
            if isinstance(summary, dict)
            else {}
        ),
        "events": [compact_run_event(item) for item in value.get("events", [])],
        "evaluations": [
            compact_evaluation(item) for item in value.get("evaluations", [])
        ],
    }


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
        raw_plan = get_json(
            base_url,
            f"/api/v2/evaluation-plans/{quote(active_plan_id, safe='')}",
        )
        plan = compact_plan(raw_plan)
        run_id = raw_plan.get("run_id")
        if isinstance(run_id, str):
            run = compact_run(
                get_json(base_url, f"/api/runs/{quote(run_id, safe='')}")
            )
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
                case_runs.append(compact_case_run(detail))

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
