"""Build and validate self-contained ReleaseEvidence for the public reference demo."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import tomllib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from agentrig import __version__
from agentrig.reporting.release_evidence import (
    ArtifactDigest,
    ArtifactPointer,
    ReleaseComponents,
    ReleaseConfiguration,
    ReleaseEvidence,
    ReleaseIdentity,
    ScenarioReleaseEvidence,
    sha256_file,
    validate_release_evidence,
)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _python_runtime_components(lock_path: Path) -> list[dict[str, Any]]:
    with lock_path.open("rb") as source:
        lock = tomllib.load(source)
    packages = [item for item in lock.get("package", []) if isinstance(item, dict)]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for package in packages:
        name = package.get("name")
        if isinstance(name, str):
            by_name.setdefault(name, []).append(package)

    roots = by_name.get("agentrig", [])
    if not roots:
        raise ValueError("uv.lock does not contain the AgentRig package")
    pending = [
        str(value["name"])
        for value in roots[0].get("dependencies", [])
        if isinstance(value, dict) and value.get("name")
    ]
    visited_names: set[str] = set()
    selected: list[dict[str, Any]] = []
    while pending:
        name = pending.pop()
        if name in visited_names:
            continue
        visited_names.add(name)
        for package in by_name.get(name, []):
            selected.append(package)
            pending.extend(
                str(value["name"])
                for value in package.get("dependencies", [])
                if isinstance(value, dict) and value.get("name")
            )

    components: dict[str, dict[str, Any]] = {}
    for package in selected:
        name = str(package.get("name") or "").strip()
        version = str(package.get("version") or "").strip()
        if not name or not version:
            raise ValueError("uv.lock contains a runtime package without name/version")
        purl = f"pkg:pypi/{quote(name, safe='._-')}@{quote(version, safe='._-')}"
        component: dict[str, Any] = {
            "type": "library",
            "bom-ref": purl,
            "name": name,
            "version": version,
            "purl": purl,
            "scope": "required",
            "properties": [{"name": "agentrig:ecosystem", "value": "python"}],
        }
        source_hash = package.get("sdist", {}).get("hash")
        if isinstance(source_hash, str) and source_hash.startswith("sha256:"):
            component["hashes"] = [
                {"alg": "SHA-256", "content": source_hash.removeprefix("sha256:")}
            ]
        components[purl] = component
    return [components[key] for key in sorted(components)]


def _npm_runtime_components(lock_path: Path) -> list[dict[str, Any]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("package-lock.json does not contain a packages index")
    components: dict[str, dict[str, Any]] = {}
    for package_path, package in packages.items():
        if not package_path or not isinstance(package, dict) or package.get("dev") is True:
            continue
        version = str(package.get("version") or "").strip()
        if not version:
            continue
        name_value = package.get("name")
        name = (
            str(name_value)
            if isinstance(name_value, str) and name_value
            else str(package_path).rsplit("node_modules/", 1)[-1]
        )
        if not name:
            raise ValueError("package-lock.json contains a runtime package without a name")
        purl = f"pkg:npm/{quote(name, safe='/._-')}@{quote(version, safe='._-')}"
        components[purl] = {
            "type": "library",
            "bom-ref": purl,
            "name": name,
            "version": version,
            "purl": purl,
            "scope": "required",
            "properties": [{"name": "agentrig:ecosystem", "value": "npm"}],
        }
    return [components[key] for key in sorted(components)]


def build_sbom(
    repository_root: Path,
    *,
    git_sha: str,
    generated_at: datetime,
) -> dict[str, Any]:
    """Build a deterministic-component CycloneDX 1.6 runtime SBOM from lock files."""

    components = [
        *_python_runtime_components(repository_root / "uv.lock"),
        *_npm_runtime_components(repository_root / "web/package-lock.json"),
    ]
    serial_number = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/ChenCJ-io/agentrig/{git_sha}",
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial_number}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at.isoformat(),
            "component": {
                "type": "application",
                "bom-ref": f"pkg:pypi/agentrig@{__version__}",
                "name": "agentrig",
                "version": __version__,
                "purl": f"pkg:pypi/agentrig@{__version__}",
            },
            "properties": [
                {"name": "agentrig:git_sha", "value": git_sha},
                {"name": "agentrig:source", "value": "locked-runtime-dependencies"},
            ],
        },
        "components": sorted(components, key=lambda item: str(item["bom-ref"])),
    }


def _node_version() -> str:
    try:
        value = subprocess.run(
            ["node", "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise ValueError("Node.js version is unavailable") from exc
    normalized = value.removeprefix("v")
    if not normalized:
        raise ValueError("Node.js returned an empty version")
    return normalized


def _public_config(
    *,
    agentrig_url: str,
    target_url: str,
) -> dict[str, Any]:
    agentrig = urlsplit(agentrig_url)
    target = urlsplit(target_url)
    return {
        "schema_version": "agentrig.public-reference-config.v1",
        "profile": "reference-ci",
        "services": {
            "agentrig": {
                "scheme": agentrig.scheme,
                "host": agentrig.hostname,
                "port": agentrig.port,
            },
            "reference_target": {
                "scheme": target.scheme,
                "host": target.hostname,
                "port": target.port,
                "workers": 1,
            },
        },
        "database": {"engine": "sqlite", "path_included": False},
        "target_network": {
            "allow_private_networks": False,
            "allowed_hosts": ["127.0.0.1", "localhost", "::1"],
        },
        "credentials": {"values_included": False, "references": []},
    }


def _scenario_records(run_manifest: dict[str, Any]) -> list[ScenarioReleaseEvidence]:
    records: list[ScenarioReleaseEvidence] = []
    scenarios = run_manifest.get("scenarios")
    if not isinstance(scenarios, dict):
        raise ValueError("reference run manifest does not contain scenarios")
    for scenario_name, scenario in scenarios.items():
        if not isinstance(scenario, dict):
            raise ValueError(f"invalid scenario record: {scenario_name}")
        run_ids = [str(value) for value in scenario.get("run_ids", [])]
        expected = json.dumps(
            scenario.get("expected"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for index, run_id in enumerate(run_ids, start=1):
            case_runs = [
                item
                for item in scenario.get("case_runs", [])
                if isinstance(item, dict) and str(item.get("run_id")) == run_id
            ]
            actual = json.dumps(
                [
                    {
                        "role": item.get("comparison_role"),
                        "status": item.get("status"),
                        "evaluation_state": item.get("evaluation_state"),
                        "error_code": item.get("error_code"),
                    }
                    for item in case_runs
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            record_name = (
                str(scenario_name) if len(run_ids) == 1 else f"{scenario_name}:attempt-{index}"
            )
            records.append(
                ScenarioReleaseEvidence(
                    name=record_name,
                    run_id=run_id,
                    case_run_ids=[str(item["id"]) for item in case_runs],
                    expected=expected,
                    actual=actual,
                )
            )
    return records


def _copy_artifact(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValueError(f"release source artifact is missing: {source}")
    shutil.copyfile(source, destination)


def _artifact(path: Path, media_type: str) -> ArtifactDigest:
    return ArtifactDigest(
        path=path.name,
        sha256=sha256_file(path),
        media_type=media_type,
    )


def build_release_bundle(
    *,
    output_dir: Path,
    repository_root: Path,
    run_manifest_path: Path,
    reference_evidence_path: Path,
    reference_markdown_path: Path,
    agentrig_url: str,
    target_url: str,
    git_sha: str,
    source_dirty: bool,
    node_version: str | None = None,
    additional_artifacts: Sequence[tuple[Path, str]] = (),
) -> Path:
    """Add locks, public config, SBOM, ReleaseEvidence, and SHA256SUMS."""

    if len(git_sha) != 40:
        raise ValueError("release evidence requires a full Git SHA")
    generated_at = datetime.now(UTC)
    copied_run_manifest = output_dir / "reference-runs.json"
    copied_uv_lock = output_dir / "uv.lock"
    copied_web_lock = output_dir / "web-package-lock.json"
    public_config_path = output_dir / "public-config.json"
    sbom_path = output_dir / "sbom.cdx.json"
    _copy_artifact(run_manifest_path, copied_run_manifest)
    _copy_artifact(repository_root / "uv.lock", copied_uv_lock)
    _copy_artifact(repository_root / "web/package-lock.json", copied_web_lock)
    _write_json(
        public_config_path,
        _public_config(agentrig_url=agentrig_url, target_url=target_url),
    )
    _write_json(
        sbom_path,
        build_sbom(repository_root, git_sha=git_sha, generated_at=generated_at),
    )

    artifacts = [
        _artifact(reference_evidence_path, "application/json"),
        _artifact(reference_markdown_path, "text/markdown"),
        _artifact(copied_run_manifest, "application/json"),
        _artifact(public_config_path, "application/json"),
        _artifact(sbom_path, "application/vnd.cyclonedx+json"),
        _artifact(copied_uv_lock, "application/toml"),
        _artifact(copied_web_lock, "application/json"),
    ]
    output_root = output_dir.resolve()
    for artifact_path, media_type in additional_artifacts:
        resolved_path = artifact_path.resolve()
        if resolved_path.parent != output_root:
            raise ValueError(
                "additional release artifacts must be direct children of output_dir"
            )
        artifacts.append(_artifact(resolved_path, media_type))
    artifact_names = [item.path for item in artifacts]
    if len(artifact_names) != len(set(artifact_names)):
        raise ValueError("release artifact paths must be unique")
    run_manifest = json.loads(copied_run_manifest.read_text(encoding="utf-8"))
    release = ReleaseEvidence(
        release=ReleaseIdentity(
            version=__version__,
            git_sha=git_sha,
            source_dirty=source_dirty,
            generated_at=generated_at,
        ),
        components=ReleaseComponents(
            profile="reference-ci",
            python=platform.python_version(),
            node=node_version or _node_version(),
            agentrig=__version__,
            agentteams=None,
            database="sqlite",
            model_identifiers=[],
        ),
        artifacts=artifacts,
        configuration=ReleaseConfiguration(
            public_config_path=public_config_path.name,
            public_config_hash=sha256_file(public_config_path),
            secret_values_included=False,
        ),
        scenarios=_scenario_records(run_manifest),
        evidence_bundle=ArtifactPointer(
            path=reference_evidence_path.name,
            sha256=sha256_file(reference_evidence_path),
        ),
        sbom=ArtifactPointer(path=sbom_path.name, sha256=sha256_file(sbom_path)),
    )
    release_manifest_path = output_dir / "release-evidence.json"
    _write_json(release_manifest_path, release.model_dump(mode="json"))

    checksum_paths = [
        *[output_dir / value.path for value in artifacts],
        release_manifest_path,
    ]
    (output_dir / "SHA256SUMS").write_text(
        "\n".join(
            f"{sha256_file(path).removeprefix('sha256:')}  {path.name}"
            for path in sorted(checksum_paths, key=lambda item: item.name)
        )
        + "\n",
        encoding="utf-8",
    )
    validate_release_evidence(
        release_manifest_path,
        expected_version=__version__,
        expected_git_sha=git_sha,
    )
    return release_manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--expected-version", default=__version__)
    validate.add_argument("--expected-git-sha")
    validate.add_argument("--require-clean-source", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = validate_release_evidence(
            args.manifest,
            expected_version=args.expected_version,
            expected_git_sha=args.expected_git_sha,
            require_clean_source=args.require_clean_source,
        )
        print(json.dumps(result.model_dump(mode="json"), indent=2))
    except (OSError, ValueError) as exc:
        print(f"[release-evidence] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
