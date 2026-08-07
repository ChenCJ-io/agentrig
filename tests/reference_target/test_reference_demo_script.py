"""Black-box acceptance test for the one-command public reference demo."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _run_demo(
    repository_root: Path,
    environment: dict[str, str],
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(repository_root / "scripts/reference_demo.sh"), *arguments],
        cwd=Path(environment["AGENTRIG_REFERENCE_STATE_DIR"]).parent,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"reference demo failed ({completed.returncode})\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def test_reference_demo_all_is_idempotent_and_exports_verified_evidence(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    state_dir = tmp_path / "reference demo state"
    target_port = _free_port()
    agentrig_port = _free_port()
    while agentrig_port == target_port:
        agentrig_port = _free_port()
    environment = {
        **os.environ,
        "AGENTRIG_REFERENCE_STATE_DIR": str(state_dir),
        "AGENTRIG_REFERENCE_TARGET_PORT": str(target_port),
        "AGENTRIG_REFERENCE_SERVER_PORT": str(agentrig_port),
        "AGENTRIG_REFERENCE_SKIP_INSTALL": "1",
        "AGENTRIG_REFERENCE_SKIP_WEB_VERIFY": "1",
    }

    try:
        first = _run_demo(repository_root, environment, "all")
        assert "verification passed" in first.stdout
        assert "evidence export complete" in first.stdout

        second = _run_demo(repository_root, environment, "setup")
        assert second.stdout.count('"unchanged"') == 6
        _run_demo(repository_root, environment, "verify")

        manifest = json.loads((state_dir / "latest-runs.json").read_text())
        assert manifest["schema_version"] == "agentrig.reference-demo-runs.v1"
        assert manifest["scenarios"]["success"]["expected"] == "pass"
        assert manifest["scenarios"]["policy-regression"]["expected"] == {
            "baseline": "pass",
            "candidate": "fail",
        }
        recovery = manifest["scenarios"]["recovery"]
        assert recovery["expected"] == {
            "attempt_1": "target_unreachable",
            "attempt_2": "pass",
        }
        assert recovery["attempt_1_preserved"] is True

        pointer = json.loads((state_dir / "latest-evidence.json").read_text())
        assert not Path(pointer["path"]).is_absolute()
        assert not Path(pointer["release_manifest"]).is_absolute()
        evidence_dir = state_dir / pointer["path"]
        bundle = json.loads((evidence_dir / "reference-evidence.json").read_text())
        assert bundle["schema_version"] == "agentrig.reference-evidence.v1"
        assert bundle["source"]["secret_payloads_included"] is False
        assert len(bundle["runs"]) == 4
        assert set(bundle["scenario_results"]) == {
            "success",
            "policy-regression",
            "recovery",
        }
        serialized_bundle = json.dumps(bundle).casefold()
        for excluded_key in ('"authorization"', '"cookie"', '"api_key"', '"secret_ref"'):
            assert excluded_key not in serialized_bundle

        release_manifest_path = state_dir / pointer["release_manifest"]
        assert release_manifest_path.parent == evidence_dir
        release = json.loads(release_manifest_path.read_text())
        assert release["schema_version"] == "agentrig.release-evidence.v1"
        assert release["release"]["git_sha"] == bundle["source"]["git_sha"]
        assert release["release"]["source_dirty"] is bundle["source"]["source_dirty"]
        assert release["components"]["profile"] == "reference-ci"
        assert release["components"]["agentteams"] is None
        assert release["configuration"]["secret_values_included"] is False
        assert len(release["artifacts"]) == 7
        assert len(release["scenarios"]) == 4
        assert {item["run_id"] for item in release["scenarios"]} == {
            run_id
            for scenario in bundle["scenario_results"].values()
            for run_id in scenario["run_ids"]
        }
        assert all(not Path(item["path"]).is_absolute() for item in release["artifacts"])
        sbom = json.loads((evidence_dir / release["sbom"]["path"]).read_text())
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["specVersion"] == "1.6"
        assert sbom["metadata"]["component"]["version"] == release["release"]["version"]
        assert len(sbom["components"]) > 10

        checksum_lines = (evidence_dir / "SHA256SUMS").read_text().splitlines()
        assert len(checksum_lines) == 8
        for line in checksum_lines:
            expected_digest, filename = line.split("  ", 1)
            actual_digest = hashlib.sha256((evidence_dir / filename).read_bytes()).hexdigest()
            assert actual_digest == expected_digest

        pointer["release_manifest"] = "../outside/release-evidence.json"
        (state_dir / "latest-evidence.json").write_text(json.dumps(pointer), encoding="utf-8")
        unsafe_pointer = _run_demo(
            repository_root,
            environment,
            "validate-evidence",
            check=False,
        )
        assert unsafe_pointer.returncode != 0
        assert "normalized relative POSIX path" in unsafe_pointer.stderr
    finally:
        _run_demo(repository_root, environment, "down", check=False)
