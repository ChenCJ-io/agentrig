"""Stable contracts for capability-driven runtime safety evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


SafetySeverity = Literal["critical", "high", "medium", "low"]
SafetyStatus = Literal["pass", "fail", "inconclusive", "skipped"]


class SafetyCaseSpec(_StrictModel):
    id: str
    risk_domain: Literal[
        "permission",
        "interrupt_resume",
        "external_execution",
        "context_compression",
        "memory",
        "workspace",
        "skill_supply_chain",
        "subagent_collaboration",
        "budget_usage",
        "multimodal",
    ]
    severity: SafetySeverity
    required_capabilities: list[str] = Field(default_factory=list)
    deterministic_rules: list[str] = Field(min_length=1)
    description: str


class SafetySuiteManifest(_StrictModel):
    schema_version: Literal["agentrig.test-suite.v1"] = "agentrig.test-suite.v1"
    id: str
    version: str
    default_profile: str
    gate_policy: str
    cases: list[SafetyCaseSpec] = Field(min_length=1)
    content_hash: str


class SafetyRuleResult(_StrictModel):
    rule: str
    status: SafetyStatus
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class SafetyCaseResult(_StrictModel):
    case_id: str
    case_run_id: str | None = None
    risk_domain: str
    severity: SafetySeverity
    status: SafetyStatus
    capability_status: Literal[
        "supported",
        "unsupported",
        "unknown",
        "not_observed",
    ]
    rules: list[SafetyRuleResult] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SafetyDomainSummary(_StrictModel):
    risk_domain: str
    total: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    inconclusive_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)


class RuntimeSafetyReport(_StrictModel):
    schema_version: Literal["agentrig.runtime-safety-report.v1"] = (
        "agentrig.runtime-safety-report.v1"
    )
    generated_at: datetime
    run_id: str
    suite_id: str
    suite_version: str
    suite_content_hash: str
    source_snapshot_hash: str
    profile_kind: Literal["reference", "live", "unknown"]
    domains: list[SafetyDomainSummary] = Field(default_factory=list)
    cases: list[SafetyCaseResult] = Field(default_factory=list)
    critical_high_failures: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    unknown_capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class SafetyGateResult(_StrictModel):
    schema_version: Literal["agentrig.runtime-safety-gate.v1"] = (
        "agentrig.runtime-safety-gate.v1"
    )
    run_id: str
    suite_content_hash: str
    outcome: Literal["passed", "blocked", "inconclusive"]
    blocking_case_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    report_source_snapshot_hash: str
