"""Run the repeatable lassist suite used by the competition recording.

This script deliberately keeps image/client side effects controlled: lassist model
inference, HTTP/SSE, sessions and tool selection are live; AgentRig injects frozen
fixture results and evaluates the captured evidence with deterministic rules.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / ".agentrig" / "competition-live" / "lassist-recording-suite.json"
TARGET_ID = "target_lassist_local"
PROFILE_ID = "profile_lassist_fixture_rule"


@dataclass(frozen=True)
class Scenario:
    case_id: str
    version: str
    expected: str
    purpose: str


SCENARIOS = (
    Scenario(
        "compat_tc_from_error_099",
        "9.2.0",
        "pass",
        "单轮背景增强正确路由到 apply_image_prompt",
    ),
    Scenario(
        "compat_tc_from_error_080",
        "9.3.0",
        "pass",
        "跨轮会话保持并撤销最近一次修图",
    ),
    Scenario(
        "compat_tc_from_error_081",
        "9.3.0",
        "pass",
        "同轮先查项目列表，再使用真实返回的 ID 打开项目",
    ),
    Scenario(
        "diagnostic_tc_from_error_081_wrong_project_id",
        "9.3.0",
        "fail",
        "保留同一真实行为，但用错误期望展示参数级失败归因",
    ),
)


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-AgentRig-Principal": "lassist-recording-suite",
            },
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - operator URL
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("POST", path, body)


def run_request(scenario: Scenario, repeat_count: int) -> dict[str, Any]:
    return {
        "case_ids": [scenario.case_id],
        "targets": [{"target_id": TARGET_ID, "version": scenario.version}],
        "profile_id": PROFILE_ID,
        "repeat_count": repeat_count,
        "overrides": {},
    }


def wait_for_run(api: Api, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    encoded = quote(run_id, safe="")
    while time.monotonic() < deadline:
        run = api.get(f"/api/runs/{encoded}")
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(1.0)
    raise TimeoutError(f"timed out waiting for Run {run_id}")


def execute_scenario(
    api: Api,
    scenario: Scenario,
    *,
    repeat_count: int,
    timeout: float,
) -> dict[str, Any]:
    request = run_request(scenario, repeat_count)
    preview = api.post("/api/runs/preview", request)
    request["expected_manifest_hash"] = preview["manifest_hash"]
    submitted = api.post("/api/runs", request)
    run_id = str(submitted["run_id"])
    run = wait_for_run(api, run_id, timeout)
    cells = api.get(f"/api/runs/{quote(run_id, safe='')}/cells")["items"]
    actual = [str(cell["evaluation_state"]) for cell in cells]
    expected_ok = bool(actual) and all(item == scenario.expected for item in actual)
    return {
        "case_id": scenario.case_id,
        "purpose": scenario.purpose,
        "version": scenario.version,
        "expected": scenario.expected,
        "run_id": run_id,
        "manifest_hash": preview["manifest_hash"],
        "run_status": run["status"],
        "cell_count": len(cells),
        "evaluation_states": actual,
        "expected_outcome_observed": expected_ok,
        "report_url": (
            f"/targets/{TARGET_ID}/evaluation/runs/{run_id}/report"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8020")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only this case ID; may be specified more than once.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat must be >= 1")
    selected = [
        scenario
        for scenario in SCENARIOS
        if not args.case_ids or scenario.case_id in args.case_ids
    ]
    missing = set(args.case_ids or []) - {scenario.case_id for scenario in selected}
    if missing:
        raise SystemExit(f"unknown recording case(s): {', '.join(sorted(missing))}")

    api = Api(args.base_url)
    target = api.get(f"/api/targets/{TARGET_ID}")
    check = api.post(f"/api/targets/{TARGET_ID}/check", {})
    if not check.get("reachable"):
        raise RuntimeError(f"lassist is not reachable: {check.get('message')}")

    results = []
    for scenario in selected:
        scenario_repeat = 1 if scenario.expected == "fail" else args.repeat
        print(f"running {scenario.case_id} x{scenario_repeat} ...", flush=True)
        result = execute_scenario(
            api,
            scenario,
            repeat_count=scenario_repeat,
            timeout=args.timeout,
        )
        results.append(result)
        state_text = ",".join(result["evaluation_states"])
        print(f"  {result['run_id']} -> {state_text}", flush=True)

    artifact = {
        "schema_version": "agentrig.lassist-recording-suite.v1",
        "generated_at_epoch": time.time(),
        "target": {
            "id": target["id"],
            "name": target["name"],
            "driver_type": target["driver_type"],
            "endpoint": target["endpoint"],
        },
        "execution_boundary": {
            "model_inference": "live lassist",
            "protocol": "live HTTP/SSE",
            "session_and_tool_selection": "live lassist",
            "tool_side_effects": "controlled fixture injection",
            "evaluator": "deterministic rule",
        },
        "repeat_policy": {
            "semantic_success_cases": args.repeat,
            "deterministic_diagnostic_cases": 1,
        },
        "results": results,
        "passed": all(item["expected_outcome_observed"] for item in results),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(f"artifact={args.output}")
    if not artifact["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
