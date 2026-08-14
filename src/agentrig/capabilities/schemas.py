"""Strict versioned contracts for frozen runtime capability evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CapabilitySourceStatus = Literal[
    "declared",
    "observed",
    "verified",
    "unsupported",
    "unknown",
]
CapabilityComparison = Literal[
    "comparable",
    "warning_difference",
    "incomparable_environment",
    "unknown",
]
CapabilityPartition = Literal[
    "runtime",
    "model",
    "tools",
    "skills",
    "permissions",
    "workspace",
    "memory",
    "collaboration",
]


def _default_blocking_partitions() -> list[CapabilityPartition]:
    return [
        "runtime",
        "model",
        "tools",
        "skills",
        "permissions",
        "workspace",
        "memory",
    ]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CapabilitySource(_StrictModel):
    driver: str
    probe_version: str = "1"
    target_config_hash: str


class CapabilityFeature(_StrictModel):
    status: CapabilitySourceStatus
    value: bool | str | int | float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class CapabilityPartitionHashes(_StrictModel):
    runtime_hash: str
    model_hash: str
    tools_hash: str
    skills_hash: str
    permissions_hash: str
    workspace_hash: str
    memory_hash: str
    collaboration_hash: str


class TargetCapabilitySnapshot(_StrictModel):
    schema_version: Literal["agentrig.target-capability-snapshot.v1"] = (
        "agentrig.target-capability-snapshot.v1"
    )
    snapshot_id: str
    case_run_id: str
    collected_at: datetime
    collection_status: Literal[
        "complete",
        "partial",
        "unavailable",
        "invalid",
        "legacy_unavailable",
    ]
    source: CapabilitySource
    runtime: dict[str, Any] = Field(default_factory=dict)
    models: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    workspace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    collaboration: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, CapabilityFeature] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    partition_hashes: CapabilityPartitionHashes
    snapshot_hash: str


class CapabilityComparisonPolicy(_StrictModel):
    schema_version: Literal["agentrig.capability-comparison-policy.v1"] = (
        "agentrig.capability-comparison-policy.v1"
    )
    blocking_partitions: list[CapabilityPartition] = Field(
        default_factory=_default_blocking_partitions
    )
    allowed_differences: list[str] = Field(default_factory=list)
    unknown_is_incomparable: bool = True


class CapabilityDifference(_StrictModel):
    path: str
    baseline_hash: str | None
    candidate_hash: str | None
    severity: Literal["blocking", "warning"]
    allowed: bool = False
    reason: str


class CapabilityDiff(_StrictModel):
    schema_version: Literal["agentrig.target-capability-diff.v1"] = (
        "agentrig.target-capability-diff.v1"
    )
    baseline_snapshot_hash: str | None
    candidate_snapshot_hash: str | None
    comparison: CapabilityComparison
    differences: list[CapabilityDifference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
