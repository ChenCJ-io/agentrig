"""Stable ReleaseEvidence contract and offline integrity validation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA256_PREFIX = "sha256:"
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "secret_ref",
    "token",
}


def sha256_file(path: Path) -> str:
    """Return a lowercase, prefixed SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{_SHA256_PREFIX}{digest.hexdigest()}"


def _relative_artifact_path(value: str) -> str:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or value != candidate.as_posix():
        raise ValueError("artifact path must be a normalized relative POSIX path")
    if value in {"", "."}:
        raise ValueError("artifact path must name a file")
    return value


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseIdentity(_StrictModel):
    version: str = Field(min_length=1)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_dirty: bool
    generated_at: datetime

    @field_validator("version")
    @classmethod
    def version_is_specific(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized.casefold() in {"latest", "unknown"}:
            raise ValueError("release version must be an explicit package version")
        return normalized

    @field_validator("generated_at")
    @classmethod
    def generated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


class ReleaseComponents(_StrictModel):
    profile: Literal["reference-ci", "reference-agentteams"]
    python: str = Field(min_length=1)
    node: str = Field(min_length=1)
    agentrig: str = Field(min_length=1)
    agentteams: str | None = None
    database: str = Field(min_length=1)
    model_identifiers: list[str] = Field(default_factory=list)

    @field_validator("python", "node", "agentrig", "database")
    @classmethod
    def component_version_is_specific(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized.casefold() in {"latest", "unknown"}:
            raise ValueError("component versions must be explicit")
        return normalized

    @field_validator("agentteams")
    @classmethod
    def optional_agentteams_version_is_specific(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or normalized.casefold() in {"latest", "unknown"}:
            raise ValueError("AgentTeams version must be explicit when present")
        return normalized

    @field_validator("model_identifiers")
    @classmethod
    def model_identifiers_are_unique(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("model identifiers cannot be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("model identifiers must be unique")
        return cleaned


class ArtifactDigest(_StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: str = Field(min_length=1)

    _safe_path = field_validator("path")(_relative_artifact_path)


class ReleaseConfiguration(_StrictModel):
    public_config_path: str
    public_config_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    secret_values_included: Literal[False] = False

    _safe_path = field_validator("public_config_path")(_relative_artifact_path)


class ScenarioReleaseEvidence(_StrictModel):
    name: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    case_run_ids: list[str] = Field(min_length=1)
    expected: str = Field(min_length=1)
    actual: str = Field(min_length=1)

    @field_validator("case_run_ids")
    @classmethod
    def case_run_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("case_run_ids must be unique per scenario record")
        return value


class ArtifactPointer(_StrictModel):
    path: str
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    _safe_path = field_validator("path")(_relative_artifact_path)


class ReleaseEvidence(_StrictModel):
    schema_version: Literal["agentrig.release-evidence.v1"] = "agentrig.release-evidence.v1"
    release: ReleaseIdentity
    components: ReleaseComponents
    artifacts: list[ArtifactDigest] = Field(min_length=1)
    configuration: ReleaseConfiguration
    scenarios: list[ScenarioReleaseEvidence] = Field(min_length=1)
    evidence_bundle: ArtifactPointer
    sbom: ArtifactPointer

    @model_validator(mode="after")
    def artifact_and_run_identifiers_are_unique(self) -> ReleaseEvidence:
        artifact_paths = [item.path for item in self.artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("artifact paths must be unique")
        scenario_names = [item.name for item in self.scenarios]
        if len(scenario_names) != len(set(scenario_names)):
            raise ValueError("scenario names must be unique")
        run_ids = [item.run_id for item in self.scenarios]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("scenario Run IDs must be unique")
        case_run_ids = [
            case_run_id for scenario in self.scenarios for case_run_id in scenario.case_run_ids
        ]
        if len(case_run_ids) != len(set(case_run_ids)):
            raise ValueError("scenario CaseRun IDs must be globally unique")
        return self


class ReleaseValidationResult(_StrictModel):
    schema_version: Literal["agentrig.release-validation.v1"] = "agentrig.release-validation.v1"
    valid: Literal[True] = True
    manifest_path: str
    version: str
    git_sha: str
    source_dirty: bool
    artifact_count: int
    scenario_count: int


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON artifact: {path.name}") from exc


def _artifact_path(bundle_root: Path, relative_path: str) -> Path:
    candidate = (bundle_root / relative_path).resolve()
    resolved_root = bundle_root.resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise ValueError(f"artifact escapes release bundle: {relative_path}")
    if not candidate.is_file():
        raise ValueError(f"release artifact is missing: {relative_path}")
    return candidate


def _reject_sensitive_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _SENSITIVE_KEYS:
                raise ValueError(f"sensitive key is forbidden in release evidence: {path}.{key}")
            _reject_sensitive_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_keys(item, path=f"{path}[{index}]")


def _validate_sha256sums(manifest_path: Path, manifest: ReleaseEvidence) -> None:
    bundle_root = manifest_path.parent
    checksum_path = _artifact_path(bundle_root, "SHA256SUMS")
    expected = {item.path: item.sha256.removeprefix(_SHA256_PREFIX) for item in manifest.artifacts}
    if manifest_path.name in expected or checksum_path.name in expected:
        raise ValueError("release artifact index contains a reserved bundle filename")
    expected[manifest_path.name] = sha256_file(manifest_path).removeprefix(_SHA256_PREFIX)

    actual: dict[str, str] = {}
    for line_number, line in enumerate(
        checksum_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        parts = line.split("  ", 1)
        if len(parts) != 2 or re.fullmatch(r"[0-9a-f]{64}", parts[0]) is None:
            raise ValueError(f"invalid SHA256SUMS line {line_number}")
        relative_path = _relative_artifact_path(parts[1])
        if relative_path in actual:
            raise ValueError(f"duplicate SHA256SUMS entry: {relative_path}")
        actual[relative_path] = parts[0]

    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        mismatched = sorted(
            path for path in set(actual) & set(expected) if actual[path] != expected[path]
        )
        details = ", ".join(
            value
            for value in (
                f"missing={missing}" if missing else "",
                f"unexpected={unexpected}" if unexpected else "",
                f"mismatched={mismatched}" if mismatched else "",
            )
            if value
        )
        raise ValueError(f"SHA256SUMS does not match the release bundle: {details}")


def validate_release_evidence(
    manifest_path: Path,
    *,
    expected_version: str | None = None,
    expected_git_sha: str | None = None,
    require_clean_source: bool = False,
) -> ReleaseValidationResult:
    """Validate a self-contained release evidence directory without network access."""

    raw_manifest = _read_json(manifest_path)
    manifest = ReleaseEvidence.model_validate(raw_manifest)
    if expected_version is not None and manifest.release.version != expected_version:
        raise ValueError(
            f"release version mismatch: {manifest.release.version} != {expected_version}"
        )
    if manifest.components.agentrig != manifest.release.version:
        raise ValueError("AgentRig component version does not match release version")
    if expected_git_sha is not None and manifest.release.git_sha != expected_git_sha:
        raise ValueError("release Git SHA does not match the expected revision")
    if require_clean_source and manifest.release.source_dirty:
        raise ValueError("release evidence was generated from a dirty source tree")
    if manifest.configuration.secret_values_included:
        raise ValueError("release configuration must not contain secret values")

    bundle_root = manifest_path.parent
    artifact_map = {item.path: item for item in manifest.artifacts}
    for artifact in manifest.artifacts:
        path = _artifact_path(bundle_root, artifact.path)
        if sha256_file(path) != artifact.sha256:
            raise ValueError(f"release artifact digest mismatch: {artifact.path}")
    _validate_sha256sums(manifest_path, manifest)

    for label, pointer in (
        ("evidence bundle", manifest.evidence_bundle),
        ("SBOM", manifest.sbom),
    ):
        indexed_artifact = artifact_map.get(pointer.path)
        if indexed_artifact is None or indexed_artifact.sha256 != pointer.sha256:
            raise ValueError(f"{label} pointer does not match the artifact index")

    public_config = artifact_map.get(manifest.configuration.public_config_path)
    if public_config is None:
        raise ValueError("public configuration is absent from the artifact index")
    if public_config.sha256 != manifest.configuration.public_config_hash:
        raise ValueError("public configuration hash does not match the artifact index")

    evidence = _read_json(_artifact_path(bundle_root, manifest.evidence_bundle.path))
    if evidence.get("schema_version") != "agentrig.reference-evidence.v1":
        raise ValueError("release evidence bundle has an unsupported schema")
    evidence_source = evidence.get("source")
    if not isinstance(evidence_source, dict):
        raise ValueError("release evidence bundle is missing source metadata")
    if evidence_source.get("git_sha") != manifest.release.git_sha:
        raise ValueError("evidence bundle Git SHA does not match the release")
    if evidence_source.get("source_dirty") is not manifest.release.source_dirty:
        raise ValueError("evidence bundle source state does not match the release")
    if evidence_source.get("profile") != manifest.components.profile:
        raise ValueError("evidence bundle profile does not match the release")
    evidence_run_ids = {
        str(run_id)
        for value in evidence.get("scenario_results", {}).values()
        for run_id in value.get("run_ids", [])
    }
    manifest_run_ids = {item.run_id for item in manifest.scenarios}
    if evidence_run_ids != manifest_run_ids:
        raise ValueError("release scenario Run IDs do not match the evidence bundle")
    evidence_case_runs = {
        str(case_run.get("id")): case_run
        for value in evidence.get("scenario_results", {}).values()
        for case_run in value.get("case_runs", [])
        if isinstance(case_run, dict) and case_run.get("id")
    }
    manifest_case_run_ids = {
        case_run_id for scenario in manifest.scenarios for case_run_id in scenario.case_run_ids
    }
    if set(evidence_case_runs) != manifest_case_run_ids:
        raise ValueError("release scenario CaseRun IDs do not match the evidence bundle")
    for scenario in manifest.scenarios:
        if any(
            str(evidence_case_runs[case_run_id].get("run_id")) != scenario.run_id
            for case_run_id in scenario.case_run_ids
        ):
            raise ValueError("release scenario CaseRun does not belong to its declared Run")

    sbom = _read_json(_artifact_path(bundle_root, manifest.sbom.path))
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise ValueError("release SBOM must use CycloneDX 1.6")
    sbom_version = sbom.get("metadata", {}).get("component", {}).get("version")
    if sbom_version != manifest.release.version:
        raise ValueError("SBOM component version does not match the release")
    sbom_properties = sbom.get("metadata", {}).get("properties", [])
    sbom_git_shas = {
        item.get("value")
        for item in sbom_properties
        if isinstance(item, dict) and item.get("name") == "agentrig:git_sha"
    }
    if sbom_git_shas != {manifest.release.git_sha}:
        raise ValueError("SBOM Git SHA does not match the release")

    public_config_value = _read_json(
        _artifact_path(bundle_root, manifest.configuration.public_config_path)
    )
    if public_config_value.get("schema_version") != "agentrig.public-reference-config.v1":
        raise ValueError("release public configuration has an unsupported schema")
    if public_config_value.get("profile") != manifest.components.profile:
        raise ValueError("public configuration profile does not match the release")
    if public_config_value.get("credentials", {}).get("values_included") is not False:
        raise ValueError("public configuration must explicitly exclude credential values")

    for artifact in manifest.artifacts:
        if artifact.media_type == "application/json" or artifact.media_type.endswith("+json"):
            _reject_sensitive_keys(
                _read_json(_artifact_path(bundle_root, artifact.path)),
                path=f"$[{artifact.path}]",
            )
    _reject_sensitive_keys(raw_manifest)

    return ReleaseValidationResult(
        manifest_path=manifest_path.name,
        version=manifest.release.version,
        git_sha=manifest.release.git_sha,
        source_dirty=manifest.release.source_dirty,
        artifact_count=len(manifest.artifacts),
        scenario_count=len(manifest.scenarios),
    )
