"""Run one real Manager → lassist → Workers competition scenario via HTTP."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

SCENARIOS = {
    "success": {
        "title": "Competition acceptance · successful regression",
        "case_id": "case_lassist_three_agent_demo",
        "expected": "pass",
        "prompt": (
            "使用 target_lassist_local、profile_lassist_agentteams 和已批准用例 "
            "case_lassist_three_agent_demo，生成一次评测计划。不要扩大范围。"
        ),
    },
    "failure": {
        "title": "Competition acceptance · confirmation policy",
        "case_id": "case_lassist_confirmation_gate_failure",
        "expected": "fail",
        "prompt": (
            "只运行已批准用例 case_lassist_confirmation_gate_failure，使用本机 lassist "
            "和当前 AgentTeams Profile，验证图片编辑前的二次确认策略。"
        ),
    },
}


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode()
        request = Request(
            f"{self.base_url}{path}",
            data=payload,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-AgentRig-Principal": "competition-acceptance",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator URL
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, body)


def wait_for(
    description: str,
    timeout: float,
    probe: Callable[[], Any | None],
) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value is not None:
                return value
        except Exception as exc:  # transient remote state is reported at timeout
            last_error = exc
        time.sleep(1.5)
    suffix = f"; last error: {last_error}" if last_error is not None else ""
    raise TimeoutError(f"timed out waiting for {description}{suffix}")


def run_scenario(api: Api, scenario_name: str, timeout: float) -> dict[str, Any]:
    scenario = SCENARIOS[scenario_name]
    session = api.post(
        "/api/v2/assistant/sessions",
        {"title": scenario["title"], "workspace_id": "competition"},
    )
    session_id = str(session["id"])
    encoded_session = quote(session_id, safe="")
    wait_for(
        "Matrix room",
        60,
        lambda: (
            value
            if (value := api.get(f"/api/v2/assistant/sessions/{encoded_session}"))["matrix_room_id"]
            else None
        ),
    )

    api.post(
        f"/api/v2/assistant/sessions/{encoded_session}/messages",
        {
            "client_message_id": str(uuid.uuid4()),
            "content": scenario["prompt"],
            "active_plan_id": None,
        },
    )

    plan_id = wait_for(
        "Manager evaluation plan",
        timeout,
        lambda: api.get(f"/api/v2/assistant/sessions/{encoded_session}").get("active_plan_id"),
    )
    plan = api.get(f"/api/v2/evaluation-plans/{quote(str(plan_id), safe='')}")
    selected_cases = plan.get("selection", {}).get("case_ids")
    if selected_cases != [scenario["case_id"]]:
        raise RuntimeError(
            f"Manager selected {selected_cases!r}; expected {[scenario['case_id']]!r}"
        )

    confirmation = api.post(
        f"/api/v2/assistant/sessions/{encoded_session}/messages",
        {
            "client_message_id": str(uuid.uuid4()),
            "content": f"确认执行 {plan_id} revision {plan['revision']}",
            "active_plan_id": plan_id,
        },
    )
    api.post(
        f"/api/v2/evaluation-plans/{quote(str(plan_id), safe='')}/confirm",
        {
            "confirmation_event_id": confirmation["event_id"],
            "confirmed_by": "competition-acceptance",
        },
    )
    submission = api.post(
        f"/api/v2/evaluation-plans/{quote(str(plan_id), safe='')}/submit",
        {"idempotency_key": str(uuid.uuid4())},
    )
    run_id = str(submission["run"]["run_id"])
    encoded_run = quote(run_id, safe="")

    run = wait_for(
        "Run completion",
        timeout,
        lambda: (
            value
            if (value := api.get(f"/api/runs/{encoded_run}"))["status"]
            in {"completed", "failed", "cancelled"}
            else None
        ),
    )
    case_page = api.get(f"/api/runs/{encoded_run}/case-runs?limit=10")
    if len(case_page.get("items", [])) != 1:
        raise RuntimeError(f"expected one CaseRun, received {case_page!r}")
    case_run = case_page["items"][0]
    if case_run["evaluation_state"] != scenario["expected"]:
        raise RuntimeError(
            f"expected {scenario['expected']} verdict, got "
            f"{case_run['evaluation_state']}: {case_run}"
        )

    def worker_evidence() -> list[dict[str, Any]] | None:
        page = api.get(f"/api/v2/assistant/sessions/{encoded_session}/agent-invocations?limit=10")
        items = page.get("items", [])
        roles = {item["agent_role"] for item in items}
        complete = all(
            item.get("request_event_id") and item.get("response_event_id") for item in items
        )
        return items if roles == {"simulation_curator", "evidence_judge"} and complete else None

    invocations = wait_for("Worker Matrix receipts", 90, worker_evidence)
    detail = api.get(f"/api/case-runs/{quote(str(case_run['id']), safe='')}")
    return {
        "scenario": scenario_name,
        "session_id": session_id,
        "plan_id": plan_id,
        "run_id": run_id,
        "run_status": run["status"],
        "case_run_id": case_run["id"],
        "evaluation_state": case_run["evaluation_state"],
        "evaluations": [
            {
                "evaluator_type": value["evaluator_type"],
                "status": value["status"],
                "verdict": value["verdict"],
                "summary": value["summary"],
                "evidence_refs": value["evidence_refs"],
            }
            for value in detail.get("evaluations", [])
        ],
        "invocations": [
            {
                "id": value["id"],
                "agent_role": value["agent_role"],
                "status": value["status"],
                "request_event_id": value["request_event_id"],
                "response_event_id": value["response_event_id"],
                "result_ref": value["result_ref"],
            }
            for value in invocations
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--timeout", type=float, default=1200)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_scenario(Api(args.base_url), args.scenario, args.timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
