"""Seed, run, verify, and export the deterministic public reference demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from examples.reference_target.agentrig_assets import (
    POLICY_CASE_ID,
    RECOVERY_FAILURE_CASE_ID,
    RECOVERY_SUCCESS_CASE_ID,
    REFERENCE_PROFILE_ID,
    REFERENCE_TARGET_ID,
    SUCCESS_CASE_ID,
    canonical_cases,
    reference_profile,
    reference_target,
)
from scripts.build_reference_release import build_release_bundle
from scripts.export_competition_evidence import compact_case_run, compact_run

MANIFEST_SCHEMA = "agentrig.reference-demo-runs.v1"
EVIDENCE_SCHEMA = "agentrig.reference-evidence.v1"
TERMINAL_RUN_STATES = {"completed", "failed", "cancelled", "interrupted"}
SCENARIO_CHOICES = ("success", "policy-regression", "recovery", "all")
DEFAULT_RELEASE_POLICY_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "release-policies"
    / "default-agent-release.json"
)


class ApiError(RuntimeError):
    """Safe HTTP error that excludes raw response bodies and transport details."""

    def __init__(self, method: str, path: str, status_code: int, message: str) -> None:
        super().__init__(f"{method} {path} failed ({status_code}): {message}")
        self.status_code = status_code


class Api:
    """Small standard-library JSON client for the local AgentRig API."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        encoded_body = None
        headers = {"Accept": "application/json"}
        if body is not None:
            encoded_body = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=encoded_body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(  # noqa: S310 - operator-controlled loopback URL
                request,
                timeout=self.timeout_seconds,
            ) as response:
                if response.status == 204:
                    return None
                return json.load(response)
        except HTTPError as exc:
            message = "HTTP request rejected"
            try:
                value = json.loads(exc.read().decode())
                if isinstance(value, dict):
                    message = str(value.get("message") or value.get("code") or message)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            raise ApiError(method, path, exc.code, message) from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {type(exc.reason).__name__}") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body)

    def patch(self, path: str, body: dict[str, Any]) -> Any:
        return self.request("PATCH", path, body)

    def get_optional(self, path: str) -> Any | None:
        try:
            return self.get(path)
        except ApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def get_text(self, path: str) -> str:
        request = Request(
            f"{self.base_url}{path}",
            headers={"Accept": "text/html"},
        )
        try:
            with urlopen(  # noqa: S310 - operator-controlled loopback URL
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return response.read().decode(errors="replace")
        except HTTPError as exc:
            raise ApiError("GET", path, exc.code, "HTTP request rejected") from exc


def write_config(
    config_path: Path,
    database_path: Path,
    *,
    host: str,
    port: int,
) -> None:
    """Write the secret-free, loopback-only reference-ci configuration."""

    config_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"
    content = "\n".join(
        [
            'environment = "reference-demo"',
            "",
            "[server]",
            f"host = {json.dumps(host)}",
            f"port = {port}",
            'log_level = "INFO"',
            "",
            "[database]",
            f"url = {json.dumps(database_url)}",
            "",
            "[execution]",
            "default_concurrency = 2",
            "max_concurrency = 4",
            "max_repeat_count = 20",
            "max_cases_per_run = 20",
            "max_planned_case_runs = 100",
            "",
            "[target_network]",
            "allow_private_networks = false",
            'allowed_hosts = ["127.0.0.1", "localhost", "::1"]',
            "",
            "[reporting]",
            "max_report_case_runs = 100",
            "max_export_records = 1000",
            "",
        ]
    )
    temporary_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(config_path)


def _resource_body(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "id"}


def _same_resource(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    body = _resource_body(desired)
    actual = {key: current.get(key) for key in body}
    if isinstance(actual.get("tags"), list) and isinstance(body.get("tags"), list):
        actual["tags"] = sorted(actual["tags"])
        body["tags"] = sorted(body["tags"])
    return actual == body


def _upsert_mutable_resource(
    api: Api,
    *,
    path: str,
    desired: dict[str, Any],
) -> str:
    current = api.get_optional(path)
    if current is None:
        collection_path = path.rsplit("/", 1)[0]
        api.post(collection_path, desired)
        return "created"
    if not isinstance(current, dict):
        raise RuntimeError(f"unexpected resource response for {path}")
    if _same_resource(current, desired):
        return "unchanged"
    api.patch(path, _resource_body(desired))
    return "updated"


def seed_assets(api: Api, *, target_url: str) -> dict[str, Any]:
    """Idempotently create the canonical target, profile, and approved cases."""

    target_payload = reference_target(endpoint=target_url).model_dump(mode="json")
    profile_payload = reference_profile().model_dump(mode="json")
    result: dict[str, Any] = {
        "target": _upsert_mutable_resource(
            api,
            path=f"/api/targets/{quote(REFERENCE_TARGET_ID, safe='')}",
            desired=target_payload,
        ),
        "profile": _upsert_mutable_resource(
            api,
            path=f"/api/execution-profiles/{quote(REFERENCE_PROFILE_ID, safe='')}",
            desired=profile_payload,
        ),
        "cases": {},
    }

    for case in canonical_cases():
        payload = case.model_dump(mode="json")
        case_id = str(payload["id"])
        case_path = f"/api/test-cases/{quote(case_id, safe='')}"
        current = api.get_optional(case_path)
        action = "unchanged"
        if current is None:
            current = api.post("/api/test-cases", payload)
            action = "created"
        elif not isinstance(current, dict):
            raise RuntimeError(f"unexpected TestCase response for {case_id}")
        elif not _same_resource(current, payload):
            if current.get("review_status") == "approved":
                raise RuntimeError(
                    f"approved canonical case differs from source: {case_id}; "
                    "use a fresh reference-demo state directory"
                )
            current = api.patch(case_path, _resource_body(payload))
            action = "updated"

        if not isinstance(current, dict):
            raise RuntimeError(f"unexpected TestCase response for {case_id}")
        if current.get("review_status") != "approved":
            query = urlencode({"review_status": "approved"})
            api.post(f"{case_path}/review?{query}")
            action = f"{action}+approved"
        result["cases"][case_id] = action
    return result


def _get_external_json(url: str) -> Any:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - local target URL
            return json.load(response)
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"reference target request failed: {type(exc).__name__}") from exc


def verify_assets(
    api: Api,
    *,
    target_url: str,
    require_web: bool = True,
) -> dict[str, Any]:
    """Verify live services, canonical resources, and Target capabilities."""

    health = _get_external_json(f"{target_url.rstrip('/')}/healthz")
    catalog = _get_external_json(f"{target_url.rstrip('/')}/")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RuntimeError("reference target health contract failed")
    if not health.get("deterministic"):
        raise RuntimeError("reference target did not declare deterministic behavior")
    scenario_ids = {
        item.get("id") for item in catalog.get("scenarios", []) if isinstance(item, dict)
    }
    expected_scenarios = {
        "reference_success",
        "reference_policy_regression",
        "reference_recovery",
    }
    if scenario_ids != expected_scenarios:
        raise RuntimeError(f"reference scenario catalog mismatch: {scenario_ids!r}")

    driver_types = api.get("/api/driver-types")
    if not isinstance(driver_types, list) or not any(
        item.get("driver_type") == "http_sse" for item in driver_types if isinstance(item, dict)
    ):
        raise RuntimeError("AgentRig HTTP/SSE driver is unavailable")

    target = api.get(f"/api/targets/{quote(REFERENCE_TARGET_ID, safe='')}")
    profile = api.get(f"/api/execution-profiles/{quote(REFERENCE_PROFILE_ID, safe='')}")
    if target.get("endpoint") != target_url.rstrip("/"):
        raise RuntimeError("stored reference target endpoint does not match live target")
    if profile.get("config", {}).get("provider_chain") != [{"name": "fixture", "config": {}}]:
        raise RuntimeError("reference-ci profile must use only the fixture provider")

    checks: dict[str, Any] = {}
    for version in ("baseline", "candidate-regression"):
        query = urlencode({"version": version})
        value = api.post(f"/api/targets/{quote(REFERENCE_TARGET_ID, safe='')}/check?{query}")
        if not value.get("reachable"):
            raise RuntimeError(f"reference Target check failed for {version}: {value!r}")
        checks[version] = {
            "reachable": value["reachable"],
            "capabilities": value.get("capabilities", []),
        }

    for case_id in (
        SUCCESS_CASE_ID,
        POLICY_CASE_ID,
        RECOVERY_FAILURE_CASE_ID,
        RECOVERY_SUCCESS_CASE_ID,
    ):
        case = api.get(f"/api/test-cases/{quote(case_id, safe='')}")
        if case.get("review_status") != "approved":
            raise RuntimeError(f"canonical TestCase is not approved: {case_id}")

    if require_web:
        html = api.get_text("/")
        if "<!doctype html" not in html.casefold():
            raise RuntimeError("AgentRig Web UI is unavailable")

    return {
        "status": "ok",
        "profile": "reference-ci",
        "target": REFERENCE_TARGET_ID,
        "target_health": health,
        "target_checks": checks,
        "approved_cases": 4,
        "web": "ready" if require_web else "not-required",
    }


def _wait_for_run(api: Api, run_id: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    path = f"/api/runs/{quote(run_id, safe='')}"
    while time.monotonic() < deadline:
        run = api.get(path)
        if run.get("status") in TERMINAL_RUN_STATES:
            return run
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for Run {run_id}")


def _submit_run(
    api: Api,
    *,
    case_id: str,
    targets: list[dict[str, Any]],
    timeout_seconds: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    submitted = api.post(
        "/api/runs",
        {
            "case_ids": [case_id],
            "targets": targets,
            "profile_id": REFERENCE_PROFILE_ID,
        },
    )
    run_id = str(submitted["run_id"])
    run = _wait_for_run(api, run_id, timeout_seconds=timeout_seconds)
    page = api.get(f"/api/runs/{quote(run_id, safe='')}/case-runs?limit=10")
    case_runs = page.get("items", [])
    if not isinstance(case_runs, list) or not case_runs:
        raise RuntimeError(f"Run {run_id} did not produce any CaseRun")
    return run, case_runs


def _case_run_projection(value: dict[str, Any]) -> dict[str, Any]:
    keys = (
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
        "started_at",
        "finished_at",
    )
    return {key: value.get(key) for key in keys}


def _tool_turns(detail: dict[str, Any], tool_name: str) -> list[int]:
    return [
        int(event["payload"]["turn_position"])
        for event in detail.get("events", [])
        if event.get("event_type") == "tool_call"
        and event.get("payload", {}).get("tool_name") == tool_name
    ]


def _reference_release_reports(api: Api, run_id: str) -> dict[str, dict[str, Any]]:
    """Build and verify the report/gate chain used as public release evidence."""

    try:
        policy = json.loads(DEFAULT_RELEASE_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("default reference release policy is unavailable") from exc
    if not isinstance(policy, dict):
        raise RuntimeError("default reference release policy must be a JSON object")

    encoded_run_id = quote(run_id, safe="")
    reports = {
        "quality_report": api.get(f"/api/runs/{encoded_run_id}/quality-report"),
        "comparison_report": api.get(
            f"/api/runs/{encoded_run_id}/comparison-report"
        ),
        "release_gate": api.post(
            f"/api/runs/{encoded_run_id}/release-gate:evaluate",
            {"policy": policy},
        ),
    }
    quality = reports["quality_report"]
    comparison = reports["comparison_report"]
    gate = reports["release_gate"]
    expected_schemas = {
        "quality_report": "agentrig.quality-report.v1",
        "comparison_report": "agentrig.comparison-report.v1",
        "release_gate": "agentrig.release-gate.v1",
    }
    for name, expected_schema in expected_schemas.items():
        value = reports[name]
        if not isinstance(value, dict) or value.get("schema_version") != expected_schema:
            raise RuntimeError(f"reference {name} contract is invalid")
        if value.get("run_id") != run_id:
            raise RuntimeError(f"reference {name} belongs to a different Run")

    snapshot_hashes = {
        quality.get("source_snapshot_hash"),
        comparison.get("source_snapshot_hash"),
        gate.get("source_snapshot_hash"),
    }
    if None in snapshot_hashes or len(snapshot_hashes) != 1:
        raise RuntimeError("reference report/gate source snapshots do not match")
    summary = comparison.get("summary", {})
    if (
        summary.get("total_pairs") != 1
        or summary.get("comparable_pairs") != 1
        or summary.get("regression_count") != 1
        or summary.get("infrastructure_error_count") != 0
    ):
        raise RuntimeError("reference comparison report did not isolate one regression")
    regression_check = next(
        (
            item
            for item in gate.get("checks", [])
            if isinstance(item, dict) and item.get("name") == "outcome_regressions"
        ),
        None,
    )
    if gate.get("verdict") != "fail" or not regression_check or (
        regression_check.get("outcome") != "fail"
    ):
        raise RuntimeError("reference release gate did not block the known regression")
    return reports


def _run_success(api: Api, timeout_seconds: float) -> dict[str, Any]:
    run, case_runs = _submit_run(
        api,
        case_id=SUCCESS_CASE_ID,
        targets=[{"target_id": REFERENCE_TARGET_ID, "version": "baseline"}],
        timeout_seconds=timeout_seconds,
    )
    item = case_runs[0]
    if item.get("status") != "completed" or item.get("evaluation_state") != "pass":
        raise RuntimeError(f"reference_success did not pass: {item!r}")
    return {
        "expected": "pass",
        "run_ids": [run["id"]],
        "case_runs": [_case_run_projection(item)],
    }


def _run_policy_regression(api: Api, timeout_seconds: float) -> dict[str, Any]:
    run, case_runs = _submit_run(
        api,
        case_id=POLICY_CASE_ID,
        targets=[
            {
                "role": "baseline",
                "target_id": REFERENCE_TARGET_ID,
                "version": "baseline",
            },
            {
                "role": "candidate",
                "target_id": REFERENCE_TARGET_ID,
                "version": "candidate-regression",
            },
        ],
        timeout_seconds=timeout_seconds,
    )
    by_role = {item.get("comparison_role"): item for item in case_runs}
    if set(by_role) != {"baseline", "candidate"}:
        raise RuntimeError(f"policy A/B roles are incomplete: {case_runs!r}")
    baseline = by_role["baseline"]
    candidate = by_role["candidate"]
    if baseline.get("evaluation_state") != "pass":
        raise RuntimeError(f"policy baseline did not pass: {baseline!r}")
    if candidate.get("evaluation_state") != "fail":
        raise RuntimeError(f"policy candidate did not fail: {candidate!r}")
    if not baseline.get("comparison_pair_id") or (
        baseline.get("comparison_pair_id") != candidate.get("comparison_pair_id")
    ):
        raise RuntimeError("policy A/B CaseRuns do not share a comparison pair")

    baseline_detail = api.get(f"/api/case-runs/{quote(str(baseline['id']), safe='')}")
    candidate_detail = api.get(f"/api/case-runs/{quote(str(candidate['id']), safe='')}")
    if _tool_turns(baseline_detail, "apply_image_prompt") != [2]:
        raise RuntimeError("policy baseline did not wait until confirmation turn")
    if _tool_turns(candidate_detail, "apply_image_prompt") != [1]:
        raise RuntimeError("policy candidate did not expose the intended regression")

    release_reports = _reference_release_reports(api, str(run["id"]))

    return {
        "expected": {"baseline": "pass", "candidate": "fail"},
        "run_ids": [run["id"]],
        "comparison_pair_id": baseline["comparison_pair_id"],
        "case_runs": [
            _case_run_projection(baseline),
            _case_run_projection(candidate),
        ],
        **release_reports,
    }


def _run_recovery(api: Api, timeout_seconds: float) -> dict[str, Any]:
    failed_run, failed_case_runs = _submit_run(
        api,
        case_id=RECOVERY_FAILURE_CASE_ID,
        targets=[{"target_id": REFERENCE_TARGET_ID, "version": "baseline"}],
        timeout_seconds=timeout_seconds,
    )
    failed_before = _case_run_projection(failed_case_runs[0])
    if (
        failed_before["status"] != "failed"
        or failed_before["evaluation_state"] != "evaluation_error"
        or failed_before["error_code"] != "target_unreachable"
    ):
        raise RuntimeError(f"recovery attempt 1 did not fail as expected: {failed_before!r}")

    recovered_run, recovered_case_runs = _submit_run(
        api,
        case_id=RECOVERY_SUCCESS_CASE_ID,
        targets=[{"target_id": REFERENCE_TARGET_ID, "version": "baseline"}],
        timeout_seconds=timeout_seconds,
    )
    recovered = _case_run_projection(recovered_case_runs[0])
    failed_after_page = api.get(
        f"/api/runs/{quote(str(failed_run['id']), safe='')}/case-runs?limit=10"
    )
    failed_after = _case_run_projection(failed_after_page["items"][0])
    if failed_after != failed_before:
        raise RuntimeError("recovery attempt 2 mutated the immutable attempt 1 record")
    if recovered["status"] != "completed" or recovered["evaluation_state"] != "pass":
        raise RuntimeError(f"recovery attempt 2 did not pass: {recovered!r}")
    if failed_run["id"] == recovered_run["id"]:
        raise RuntimeError("recovery reused a Run instead of creating a new one")

    return {
        "expected": {"attempt_1": "target_unreachable", "attempt_2": "pass"},
        "run_ids": [failed_run["id"], recovered_run["id"]],
        "attempt_1_preserved": True,
        "case_runs": [failed_before, recovered],
    }


def run_scenarios(
    api: Api,
    *,
    scenario: str,
    target_url: str,
    timeout_seconds: float,
    manifest_path: Path,
) -> dict[str, Any]:
    """Run selected scenarios and persist only verified terminal summaries."""

    selected = ["success", "policy-regression", "recovery"] if scenario == "all" else [scenario]
    implementations = {
        "success": _run_success,
        "policy-regression": _run_policy_regression,
        "recovery": _run_recovery,
    }
    results: dict[str, Any] = {}
    for name in selected:
        results[name] = implementations[name](api, timeout_seconds)

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": "reference-ci",
        "target_id": REFERENCE_TARGET_ID,
        "target_url": target_url.rstrip("/"),
        "scenario_selection": scenario,
        "scenarios": results,
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _asset_hashes(target_url: str) -> dict[str, str]:
    return {
        "target": _canonical_hash(reference_target(endpoint=target_url).model_dump(mode="json")),
        "profile": _canonical_hash(reference_profile().model_dump(mode="json")),
        "cases": _canonical_hash([case.model_dump(mode="json") for case in canonical_cases()]),
    }


def _git_metadata(repository_root: Path) -> dict[str, Any]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repository_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"git_sha": revision, "source_dirty": dirty}
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {"git_sha": None, "source_dirty": None}


def _collect_run(api: Api, run_id: str) -> dict[str, Any]:
    encoded_run = quote(run_id, safe="")
    run = api.get(f"/api/runs/{encoded_run}")
    page = api.get(f"/api/runs/{encoded_run}/case-runs?limit=20")
    case_runs = []
    for summary in page.get("items", []):
        detail = api.get(f"/api/case-runs/{quote(str(summary['id']), safe='')}")
        case_runs.append(compact_case_run(detail))
    return {"run": compact_run(run), "case_runs": case_runs}


def _evidence_markdown(bundle: dict[str, Any]) -> str:
    lines = [
        "# AgentRig Public Reference Evidence",
        "",
        f"- Schema: `{bundle['schema_version']}`",
        f"- Generated: `{bundle['generated_at']}`",
        f"- Git SHA: `{bundle['source'].get('git_sha') or 'unavailable'}`",
        f"- Profile: `{bundle['source']['profile']}`",
        "- Secret payloads included: `false`",
        "",
        "| Scenario | Expected | Run IDs | CaseRun outcomes |",
        "|---|---|---|---|",
    ]
    for scenario_name, value in bundle["scenario_results"].items():
        outcomes = ", ".join(
            f"{item.get('comparison_role') or item.get('case_id')}:{item.get('evaluation_state')}"
            for item in value.get("case_runs", [])
        )
        expected = json.dumps(value.get("expected"), ensure_ascii=False, sort_keys=True)
        lines.append(
            f"| `{scenario_name}` | `{expected}` | "
            f"`{', '.join(value.get('run_ids', []))}` | `{outcomes}` |"
        )
    lines.extend(
        [
            "",
            "The recovery scenario uses two distinct Runs. Attempt 1 remains failed with",
            "`target_unreachable`; attempt 2 passes without mutating the first record.",
            "",
        ]
    )
    return "\n".join(lines)


def export_evidence(
    api: Api,
    *,
    manifest_path: Path,
    output_root: Path,
    repository_root: Path,
) -> Path:
    """Export a compact public evidence bundle plus checksums."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise RuntimeError("latest run manifest has an unsupported schema")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        raise RuntimeError("latest run manifest does not contain scenario results")

    report_artifacts: list[tuple[Path, str]] = []
    policy_regression = scenarios.get("policy-regression")
    if isinstance(policy_regression, dict):
        policy_run_ids = policy_regression.get("run_ids", [])
        if not isinstance(policy_run_ids, list) or len(policy_run_ids) != 1:
            raise RuntimeError("policy-regression must contain exactly one Run")
        release_reports = _reference_release_reports(api, str(policy_run_ids[0]))
        policy_regression.update(release_reports)

    run_ids = list(
        dict.fromkeys(
            str(run_id)
            for scenario_value in scenarios.values()
            for run_id in scenario_value.get("run_ids", [])
        )
    )
    runs = [_collect_run(api, run_id) for run_id in run_ids]
    git_metadata = _git_metadata(repository_root)
    source = {
        **git_metadata,
        "profile": manifest["profile"],
        "target_id": manifest["target_id"],
        "secret_payloads_included": False,
    }
    bundle = {
        "schema_version": EVIDENCE_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "asset_hashes": _asset_hashes(str(manifest["target_url"])),
        "scenario_results": scenarios,
        "runs": runs,
    }

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / f"reference-demo-{timestamp}"
    suffix = 1
    while output_dir.exists():
        output_dir = output_root / f"reference-demo-{timestamp}-{suffix:02d}"
        suffix += 1
    output_dir.mkdir(parents=True)

    if isinstance(policy_regression, dict):
        for key, filename in (
            ("quality_report", "quality-report.json"),
            ("comparison_report", "comparison-report.json"),
            ("release_gate", "release-gate.json"),
        ):
            artifact_path = output_dir / filename
            artifact_path.write_text(
                json.dumps(policy_regression[key], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report_artifacts.append((artifact_path, "application/json"))

    json_path = output_dir / "reference-evidence.json"
    markdown_path = output_dir / "reference-evidence.md"
    json_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_evidence_markdown(bundle), encoding="utf-8")
    release_manifest_path = build_release_bundle(
        output_dir=output_dir,
        repository_root=repository_root,
        run_manifest_path=manifest_path,
        reference_evidence_path=json_path,
        reference_markdown_path=markdown_path,
        agentrig_url=api.base_url,
        target_url=str(manifest["target_url"]),
        git_sha=str(git_metadata.get("git_sha") or ""),
        source_dirty=bool(git_metadata.get("source_dirty")),
        additional_artifacts=report_artifacts,
    )
    _write_json_atomic(
        output_root.parent / "latest-evidence.json",
        {
            "schema_version": "agentrig.reference-evidence-pointer.v1",
            "path": str(output_dir.relative_to(output_root.parent)),
            "release_manifest": str(release_manifest_path.relative_to(output_root.parent)),
            "generated_at": bundle["generated_at"],
        },
    )
    return output_dir


def _add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://127.0.0.1:8020")
    parser.add_argument("--target-url", default="http://127.0.0.1:8091")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    config = subparsers.add_parser("config")
    config.add_argument("--path", type=Path, required=True)
    config.add_argument("--database-path", type=Path, required=True)
    config.add_argument("--host", default="127.0.0.1")
    config.add_argument("--port", type=int, default=8020)

    seed = subparsers.add_parser("seed")
    _add_connection_arguments(seed)

    verify = subparsers.add_parser("verify")
    _add_connection_arguments(verify)
    verify.add_argument("--skip-web", action="store_true")

    run = subparsers.add_parser("run")
    _add_connection_arguments(run)
    run.add_argument("--scenario", choices=SCENARIO_CHOICES, default="all")
    run.add_argument("--timeout", type=float, default=30)
    run.add_argument("--manifest", type=Path, required=True)

    evidence = subparsers.add_parser("evidence")
    _add_connection_arguments(evidence)
    evidence.add_argument("--manifest", type=Path, required=True)
    evidence.add_argument("--output-root", type=Path, required=True)
    evidence.add_argument("--repository-root", type=Path, required=True)
    return parser.parse_args()


def run_cli(args: argparse.Namespace) -> int:
    if args.command == "config":
        write_config(args.path, args.database_path, host=args.host, port=args.port)
        print(args.path)
        return 0

    api = Api(args.base_url)
    if args.command == "seed":
        print(json.dumps(seed_assets(api, target_url=args.target_url), indent=2))
    elif args.command == "verify":
        print(
            json.dumps(
                verify_assets(
                    api,
                    target_url=args.target_url,
                    require_web=not args.skip_web,
                ),
                indent=2,
            )
        )
    elif args.command == "run":
        manifest = run_scenarios(
            api,
            scenario=args.scenario,
            target_url=args.target_url,
            timeout_seconds=args.timeout,
            manifest_path=args.manifest,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.command == "evidence":
        output_dir = export_evidence(
            api,
            manifest_path=args.manifest,
            output_root=args.output_root,
            repository_root=args.repository_root,
        )
        print(output_dir)
    return 0


def main() -> None:
    args = parse_args()
    try:
        raise SystemExit(run_cli(args))
    except (ApiError, RuntimeError, TimeoutError, OSError, ValueError) as exc:
        print(f"[reference-demo] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
