"""Strict, versioned release policy and gate result contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BlockingPolicy(_StrictModel):
    max_outcome_regressions: int = Field(default=0, ge=0)
    max_infrastructure_errors: int = Field(default=0, ge=0)
    max_incomplete_pairs: int = Field(default=0, ge=0)
    max_incomparable_environment_pairs: int = Field(default=0, ge=0)
    min_evidence_reference_validity: float = Field(default=1.0, ge=0, le=1)


class WarningPolicy(_StrictModel):
    max_duration_regression_ratio: float = Field(default=0.15, ge=0)
    max_token_regression_ratio: float = Field(default=0.10, ge=0)


class MinimumSamplePolicy(_StrictModel):
    comparable_pairs: int = Field(default=1, ge=1)
    latency: int = Field(default=20, ge=1)
    token: int = Field(default=1, ge=1)


class ReleasePolicy(_StrictModel):
    schema_version: Literal["agentrig.release-policy.v1"] = (
        "agentrig.release-policy.v1"
    )
    name: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(default="1.0.0", min_length=1, max_length=64)
    blocking: BlockingPolicy = Field(default_factory=BlockingPolicy)
    warnings: WarningPolicy = Field(default_factory=WarningPolicy)
    minimum_samples: MinimumSamplePolicy = Field(default_factory=MinimumSamplePolicy)


class ReleaseGateEvaluateRequest(_StrictModel):
    policy: ReleasePolicy


class ReleaseGateCheck(_StrictModel):
    name: str
    severity: Literal["blocking", "warning"]
    operator: Literal["lte", "gte"]
    actual: int | float | None
    threshold: int | float
    outcome: Literal["pass", "fail", "inconclusive", "not_evaluated"]
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class ReleaseGateResult(_StrictModel):
    schema_version: Literal["agentrig.release-gate.v1"] = "agentrig.release-gate.v1"
    generated_at: datetime
    run_id: str
    verdict: Literal["pass", "warn", "fail", "inconclusive"]
    policy_name: str
    policy_version: str
    policy_hash: str
    source_snapshot_hash: str
    result_hash: str
    checks: list[ReleaseGateCheck] = Field(default_factory=list)


def default_release_policy() -> ReleasePolicy:
    """One server-owned default shared by API, Web, CLI artifacts, and CI."""

    return ReleasePolicy(
        name="default-agent-release",
        policy_version="1.0.0",
        blocking=BlockingPolicy(
            max_outcome_regressions=0,
            max_infrastructure_errors=0,
            max_incomplete_pairs=0,
            max_incomparable_environment_pairs=0,
            min_evidence_reference_validity=1.0,
        ),
        warnings=WarningPolicy(
            max_duration_regression_ratio=0.15,
            max_token_regression_ratio=0.10,
        ),
        minimum_samples=MinimumSamplePolicy(
            comparable_pairs=1,
            latency=20,
            token=1,
        ),
    )
