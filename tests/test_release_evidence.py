"""ReleaseEvidence schema, build, integrity, and tamper checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.build_reference_release import build_release_bundle

from agentrig import __version__
from agentrig.reporting.release_evidence import (
    ArtifactDigest,
    ReleaseIdentity,
    sha256_file,
    validate_release_evidence,
)

GIT_SHA = "a" * 40
SHA256 = f"sha256:{'0' * 64}"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _build_bundle(
    tmp_path: Path,
    repository_root: Path,
    *,
    source_dirty: bool = False,
) -> Path:
    output_dir = tmp_path / "release"
    output_dir.mkdir()
    run_manifest = tmp_path / "latest-runs.json"
    reference_evidence = output_dir / "reference-evidence.json"
    reference_markdown = output_dir / "reference-evidence.md"
    scenario = {
        "expected": "pass",
        "run_ids": ["run_1"],
        "case_runs": [
            {
                "id": "case_run_1",
                "run_id": "run_1",
                "comparison_role": "candidate",
                "status": "completed",
                "evaluation_state": "pass",
                "error_code": None,
            }
        ],
    }
    _write_json(
        run_manifest,
        {
            "schema_version": "agentrig.reference-demo-runs.v1",
            "profile": "reference-ci",
            "target_id": "target_reference_http_sse",
            "target_url": "http://127.0.0.1:8091",
            "scenarios": {"success": scenario},
        },
    )
    _write_json(
        reference_evidence,
        {
            "schema_version": "agentrig.reference-evidence.v1",
            "source": {
                "git_sha": GIT_SHA,
                "source_dirty": source_dirty,
                "profile": "reference-ci",
                "secret_payloads_included": False,
            },
            "scenario_results": {"success": scenario},
            "runs": [],
        },
    )
    reference_markdown.write_text("# Reference evidence\n", encoding="utf-8")
    return build_release_bundle(
        output_dir=output_dir,
        repository_root=repository_root,
        run_manifest_path=run_manifest,
        reference_evidence_path=reference_evidence,
        reference_markdown_path=reference_markdown,
        agentrig_url="http://127.0.0.1:8020",
        target_url="http://127.0.0.1:8091",
        git_sha=GIT_SHA,
        source_dirty=source_dirty,
        node_version="20.0.0",
    )


def _rewrite_checksums(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    paths = [manifest_path.parent / item["path"] for item in manifest["artifacts"]]
    paths.append(manifest_path)
    (manifest_path.parent / "SHA256SUMS").write_text(
        "\n".join(
            f"{sha256_file(path).removeprefix('sha256:')}  {path.name}"
            for path in sorted(paths, key=lambda item: item.name)
        )
        + "\n",
        encoding="utf-8",
    )


def test_release_bundle_is_self_contained_and_validates(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = _build_bundle(tmp_path, repository_root)

    result = validate_release_evidence(
        manifest_path,
        expected_version=__version__,
        expected_git_sha=GIT_SHA,
        require_clean_source=True,
    )
    manifest = json.loads(manifest_path.read_text())
    sbom = json.loads((manifest_path.parent / manifest["sbom"]["path"]).read_text())

    assert result.valid is True
    assert result.artifact_count == 7
    assert result.scenario_count == 1
    assert manifest["configuration"]["secret_values_included"] is False
    assert manifest["components"]["agentteams"] is None
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(sbom["components"]) > 10
    assert (manifest_path.parent / "uv.lock").is_file()
    assert (manifest_path.parent / "web-package-lock.json").is_file()
    assert (manifest_path.parent / "SHA256SUMS").is_file()


def test_release_validator_rejects_tampering_and_dirty_source(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = _build_bundle(tmp_path, repository_root, source_dirty=True)

    with pytest.raises(ValueError, match="dirty source tree"):
        validate_release_evidence(manifest_path, require_clean_source=True)

    checksum_path = manifest_path.parent / "SHA256SUMS"
    original_checksums = checksum_path.read_text()
    checksum_path.write_text(f"0{original_checksums[1:]}", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256SUMS does not match"):
        validate_release_evidence(manifest_path)
    checksum_path.write_text(original_checksums, encoding="utf-8")

    evidence_path = manifest_path.parent / "reference-evidence.json"
    evidence_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_release_evidence(manifest_path)


def test_release_validator_rejects_sensitive_json_even_with_valid_hashes(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = _build_bundle(tmp_path, repository_root)
    manifest = json.loads(manifest_path.read_text())
    public_config_path = manifest_path.parent / manifest["configuration"]["public_config_path"]
    public_config = json.loads(public_config_path.read_text())
    public_config["credentials"]["api_key"] = "must-not-be-published"
    _write_json(public_config_path, public_config)
    digest = sha256_file(public_config_path)
    manifest["configuration"]["public_config_hash"] = digest
    for artifact in manifest["artifacts"]:
        if artifact["path"] == public_config_path.name:
            artifact["sha256"] = digest
    _write_json(manifest_path, manifest)
    _rewrite_checksums(manifest_path)

    with pytest.raises(ValueError, match="sensitive key is forbidden"):
        validate_release_evidence(manifest_path)


def test_release_schema_rejects_latest_version_and_unsafe_path() -> None:
    with pytest.raises(ValidationError, match="explicit package version"):
        ReleaseIdentity(
            version="latest",
            git_sha=GIT_SHA,
            source_dirty=False,
            generated_at="2026-08-07T00:00:00Z",
        )
    with pytest.raises(ValidationError, match="normalized relative POSIX path"):
        ArtifactDigest(
            path="../outside.json",
            sha256=SHA256,
            media_type="application/json",
        )
