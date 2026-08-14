"""Canonical, immutable execution manifest for one AgentRig Run."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..canonical import canonical_hash

MANIFEST_SCHEMA_VERSION: Literal["agentrig.run-manifest.v1"] = (
    "agentrig.run-manifest.v1"
)
CANONICAL_SERIALIZATION_VERSION: Literal["canonical-json.v1"] = "canonical-json.v1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SnapshotIdentity(_StrictModel):
    id: str
    snapshot_hash: str
    role: str | None = None
    version: str | None = None


class ManifestAttempt(_StrictModel):
    attempt_index: int = Field(ge=1)
    repeat_index: int = Field(ge=1)


class ManifestCell(_StrictModel):
    cell_key: str
    case_id: str
    target_id: str
    target_role: Literal["baseline", "candidate"]
    version: str | None = None
    disposition: Literal["run", "skip"]
    code: str | None = None
    message: str | None = None
    primary_evaluator: str
    case_snapshot_hash: str
    target_snapshot_hash: str
    profile_snapshot_hash: str
    attempts: list[ManifestAttempt] = Field(default_factory=list)


class RunManifest(_StrictModel):
    manifest_schema_version: Literal["agentrig.run-manifest.v1"] = MANIFEST_SCHEMA_VERSION
    canonical_serialization_version: Literal["canonical-json.v1"] = (
        CANONICAL_SERIALIZATION_VERSION
    )
    selection: dict[str, Any]
    cases: list[SnapshotIdentity]
    targets: list[SnapshotIdentity]
    profile: SnapshotIdentity
    cells: list[ManifestCell]
    repeat_count: int = Field(ge=1)
    candidate_cell_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)
    skipped_cell_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    skipped_attempt_count: int = Field(ge=0)


@dataclass(frozen=True)
class ManifestEntry:
    case_id: str
    target_id: str
    target_role: Literal["baseline", "candidate"]
    version: str | None
    repeat_index: int
    disposition: Literal["run", "skip"]
    primary_evaluator: str
    case_snapshot: dict[str, Any]
    target_snapshot: dict[str, Any]
    profile_snapshot: dict[str, Any]
    code: str | None = None
    message: str | None = None


def manifest_cell_key(entry: ManifestEntry) -> str:
    """Return a stable Cell key; repeat attempts intentionally share it."""

    return canonical_hash(
        {
            "case_id": entry.case_id,
            "target_id": entry.target_id,
            "target_role": entry.target_role,
            "version": entry.version,
            "case_snapshot_hash": canonical_hash(entry.case_snapshot),
            "target_snapshot_hash": canonical_hash(entry.target_snapshot),
            "profile_snapshot_hash": canonical_hash(entry.profile_snapshot),
            "primary_evaluator": entry.primary_evaluator,
        }
    )


def build_run_manifest(
    *,
    selection: dict[str, Any],
    case_snapshots: list[dict[str, Any]],
    target_snapshots: Sequence[tuple[str, dict[str, Any]]],
    profile_id: str,
    profile_snapshot: dict[str, Any],
    repeat_count: int,
    entries: list[ManifestEntry],
) -> RunManifest:
    """Build one deterministic manifest without persistence or runtime I/O."""

    grouped: dict[str, list[ManifestEntry]] = {}
    for entry in entries:
        grouped.setdefault(manifest_cell_key(entry), []).append(entry)

    cells: list[ManifestCell] = []
    for cell_key, grouped_entries in grouped.items():
        ordered = sorted(grouped_entries, key=lambda item: item.repeat_index)
        first = ordered[0]
        cells.append(
            ManifestCell(
                cell_key=cell_key,
                case_id=first.case_id,
                target_id=first.target_id,
                target_role=first.target_role,
                version=first.version,
                disposition=first.disposition,
                code=first.code,
                message=first.message,
                primary_evaluator=first.primary_evaluator,
                case_snapshot_hash=canonical_hash(first.case_snapshot),
                target_snapshot_hash=canonical_hash(first.target_snapshot),
                profile_snapshot_hash=canonical_hash(first.profile_snapshot),
                attempts=[
                    ManifestAttempt(
                        attempt_index=item.repeat_index,
                        repeat_index=item.repeat_index,
                    )
                    for item in ordered
                ],
            )
        )
    cells.sort(
        key=lambda item: (
            item.case_id,
            item.target_role,
            item.target_id,
            item.version or "",
            item.cell_key,
        )
    )

    cases_by_identity: dict[tuple[str, str], SnapshotIdentity] = {}
    for snapshot in case_snapshots:
        identity = SnapshotIdentity(
            id=str(snapshot.get("id") or "unknown-case"),
            snapshot_hash=canonical_hash(snapshot),
        )
        cases_by_identity[(identity.id, identity.snapshot_hash)] = identity

    targets = [
        SnapshotIdentity(
            id=str(snapshot.get("id") or "unknown-target"),
            role=role,
            version=(str(snapshot["version"]) if snapshot.get("version") is not None else None),
            snapshot_hash=canonical_hash(snapshot),
        )
        for role, snapshot in target_snapshots
    ]
    targets.sort(key=lambda item: (item.role or "", item.id, item.version or ""))

    runnable = [item for item in cells if item.disposition == "run"]
    skipped = [item for item in cells if item.disposition == "skip"]
    return RunManifest(
        selection=selection,
        cases=sorted(
            cases_by_identity.values(),
            key=lambda item: (item.id, item.snapshot_hash),
        ),
        targets=targets,
        profile=SnapshotIdentity(
            id=profile_id,
            snapshot_hash=canonical_hash(profile_snapshot),
        ),
        cells=cells,
        repeat_count=repeat_count,
        candidate_cell_count=len(cells),
        cell_count=len(runnable),
        skipped_cell_count=len(skipped),
        attempt_count=sum(len(item.attempts) for item in runnable),
        skipped_attempt_count=sum(len(item.attempts) for item in skipped),
    )


def run_manifest_hash(manifest: RunManifest) -> str:
    return canonical_hash(manifest)
