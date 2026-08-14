"""Version-isolated AgentTeams profiles and reproducible compatibility evidence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...canonical import canonical_hash


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentTeamsProfileManifest(_StrictModel):
    schema_version: Literal["agentrig.agentteams-profile.v1"] = (
        "agentrig.agentteams-profile.v1"
    )
    profile: Literal["v1.1.2-competition", "v1.2.2-current"]
    agentteams_version: Literal["v1.1.2", "v1.2.2"]
    source_git_sha: str = Field(min_length=40, max_length=64)
    runtime_name: Literal["openclaw", "qwenpaw"]
    resource_api_version: Literal["hiclaw.io/v1beta1", "agentteams.io/v1beta1"]
    resource_schema_hash: str
    controller_image: str
    runtime_images: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str]
    historical_read_only: bool = False

    @model_validator(mode="after")
    def profile_contract_is_consistent(self) -> AgentTeamsProfileManifest:
        expected = {
            "v1.1.2-competition": (
                "v1.1.2",
                "hiclaw.io/v1beta1",
                "openclaw",
            ),
            "v1.2.2-current": (
                "v1.2.2",
                "agentteams.io/v1beta1",
                "qwenpaw",
            ),
        }[self.profile]
        actual = (
            self.agentteams_version,
            self.resource_api_version,
            self.runtime_name,
        )
        if actual != expected:
            raise ValueError(
                "AgentTeams profile/version/API/runtime mismatch; implicit fallback is forbidden"
            )
        if self.profile == "v1.1.2-competition" and not self.historical_read_only:
            raise ValueError("the v1.1.2 competition profile must remain read-only")
        if self.profile == "v1.2.2-current":
            images = [self.controller_image, *self.runtime_images.values()]
            if any("@sha256:" not in image for image in images):
                raise ValueError(
                    "the v1.2.2 profile requires immutable multi-arch image digests"
                )
        return self


class AgentTeamsSkillEvidence(_StrictModel):
    role: Literal["manager", "curator", "judge"]
    skill_id: str
    contract_version: str
    local_package_hash: str
    assigned: bool
    observed_package_hash: str | None = None
    enabled: bool | None = None
    canary_succeeded: bool | None = None
    matrix_event_id: str | None = None

    @property
    def verified(self) -> bool:
        return (
            self.assigned
            and self.observed_package_hash == self.local_package_hash
            and self.enabled is True
            and self.canary_succeeded is True
        )


class AgentTeamsMembershipEvidence(_StrictModel):
    room_id_hash: str
    expected_members: list[str] = Field(default_factory=list)
    observed_members: list[str] = Field(default_factory=list)
    private_room_verified: bool = False

    @property
    def converged(self) -> bool:
        return (
            sorted(set(self.expected_members)) == sorted(set(self.observed_members))
            and self.private_room_verified
        )


class AgentTeamsInvocationEvidence(_StrictModel):
    invocation_id: str
    role: Literal["manager", "curator", "judge"]
    assigned_agent: str
    terminal_status: Literal["completed", "failed", "timed_out", "cancelled"]
    correlation_verified: bool
    duplicate_side_effects: int = Field(default=0, ge=0)


class AgentTeamsObservation(_StrictModel):
    """Immutable, operator-produced input to one compatibility report."""

    schema_version: Literal["agentrig.agentteams-observation.v1"] = (
        "agentrig.agentteams-observation.v1"
    )
    observed_at: datetime
    runtime: dict[str, Any]
    skills: list[AgentTeamsSkillEvidence] = Field(default_factory=list)
    memberships: list[AgentTeamsMembershipEvidence] = Field(default_factory=list)
    invocations: list[AgentTeamsInvocationEvidence] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class AgentTeamsCapabilityReport(_StrictModel):
    schema_version: Literal["agentrig.agentteams-compat-report.v1"] = (
        "agentrig.agentteams-compat-report.v1"
    )
    profile: str
    agentteams_version: str
    runtime_name: str
    runtime_version: str | None = None
    resource_api_version: str
    resource_schema_hash: str
    component_images: dict[str, str] = Field(default_factory=dict)
    manager_id: str
    worker_ids: list[str] = Field(default_factory=list)
    skill_delivery_mode: str
    room_membership_mode: str
    transport_health: Literal["healthy", "degraded", "unavailable", "not_observed"]
    skills: list[AgentTeamsSkillEvidence] = Field(default_factory=list)
    memberships: list[AgentTeamsMembershipEvidence] = Field(default_factory=list)
    invocations: list[AgentTeamsInvocationEvidence] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    source_git_sha: str
    source_snapshot_hash: str
    observed_at: datetime
    result_hash: str


class AgentTeamsAdapter(ABC):
    """Keep external version branches out of the AgentRig execution domains."""

    def __init__(self, manifest: AgentTeamsProfileManifest) -> None:
        self.manifest = manifest

    @property
    @abstractmethod
    def skill_delivery_mode(self) -> str: ...

    @property
    @abstractmethod
    def room_membership_mode(self) -> str: ...

    def validate_resources(
        self,
        resources: list[dict[str, Any]],
        schema: dict[str, Any],
    ) -> None:
        validator = Draft202012Validator(schema)
        for index, resource in enumerate(resources):
            errors = sorted(validator.iter_errors(resource), key=lambda item: list(item.path))
            if errors:
                message = "; ".join(error.message for error in errors)
                raise ValueError(f"AgentTeams resource[{index}] is invalid: {message}")
            if resource.get("apiVersion") != self.manifest.resource_api_version:
                raise ValueError("resource API version does not match selected profile")

    def capability_report(
        self,
        *,
        runtime_observation: dict[str, Any],
        skills: list[AgentTeamsSkillEvidence] | None = None,
        memberships: list[AgentTeamsMembershipEvidence] | None = None,
        invocations: list[AgentTeamsInvocationEvidence] | None = None,
        evidence_refs: list[str] | None = None,
        observed_at: datetime | None = None,
    ) -> AgentTeamsCapabilityReport:
        skill_items = list(skills or [])
        membership_items = list(memberships or [])
        invocation_items = list(invocations or [])
        failures: list[str] = []
        limitations: list[str] = []
        if runtime_observation.get("version") != self.manifest.agentteams_version:
            failures.append("runtime_version_mismatch")
        if runtime_observation.get("resource_api_version") != self.manifest.resource_api_version:
            failures.append("resource_api_version_mismatch")
        if self.manifest.profile == "v1.2.2-current":
            failures.extend(
                f"skill_drift:{item.role}:{item.skill_id}"
                for item in skill_items
                if not item.verified
            )
            if membership_items and not all(item.converged for item in membership_items):
                failures.append("room_membership_not_converged")
            if not skill_items:
                limitations.append("skill_distribution_not_observed")
        if not invocation_items:
            limitations.append("invocation_route_not_observed")
        if any(
            not item.correlation_verified or item.duplicate_side_effects
            for item in invocation_items
        ):
            failures.append("invocation_atomicity_failed")
        snapshot = {
            "manifest": self.manifest.model_dump(mode="json"),
            "runtime": runtime_observation,
            "skills": [item.model_dump(mode="json") for item in skill_items],
            "memberships": [item.model_dump(mode="json") for item in membership_items],
            "invocations": [item.model_dump(mode="json") for item in invocation_items],
            "evidence_refs": sorted(set(evidence_refs or [])),
        }
        report_values: dict[str, Any] = {
            "schema_version": "agentrig.agentteams-compat-report.v1",
            "profile": self.manifest.profile,
            "agentteams_version": self.manifest.agentteams_version,
            "runtime_name": self.manifest.runtime_name,
            "runtime_version": (
                str(runtime_observation["runtime_version"])
                if runtime_observation.get("runtime_version")
                else None
            ),
            "resource_api_version": self.manifest.resource_api_version,
            "resource_schema_hash": self.manifest.resource_schema_hash,
            "component_images": {
                "controller": self.manifest.controller_image,
                **self.manifest.runtime_images,
            },
            "manager_id": self.manifest.roles["manager"],
            "worker_ids": [
                self.manifest.roles[role]
                for role in ("curator", "judge")
                if role in self.manifest.roles
            ],
            "skill_delivery_mode": self.skill_delivery_mode,
            "room_membership_mode": self.room_membership_mode,
            "transport_health": str(
                runtime_observation.get("transport_health") or "not_observed"
            ),
            "skills": skill_items,
            "memberships": membership_items,
            "invocations": invocation_items,
            "failures": sorted(set(failures)),
            "limitations": sorted(set(limitations)),
            "evidence_refs": sorted(set(evidence_refs or [])),
            "source_git_sha": self.manifest.source_git_sha,
            "source_snapshot_hash": canonical_hash(snapshot),
            "observed_at": observed_at or datetime.now(timezone.utc),
        }
        stable_result = {
            key: value
            for key, value in report_values.items()
            if key != "observed_at"
        }
        stable_result["skills"] = [
            item.model_dump(mode="json") for item in skill_items
        ]
        stable_result["memberships"] = [
            item.model_dump(mode="json") for item in membership_items
        ]
        stable_result["invocations"] = [
            item.model_dump(mode="json") for item in invocation_items
        ]
        return AgentTeamsCapabilityReport(
            **report_values,
            result_hash=canonical_hash(stable_result),
        )


class LegacyAgentTeams112Adapter(AgentTeamsAdapter):
    @property
    def skill_delivery_mode(self) -> str:
        return "immutable_local_package"

    @property
    def room_membership_mode(self) -> str:
        return "legacy_manager_invite"


class AgentTeams122Adapter(AgentTeamsAdapter):
    @property
    def skill_delivery_mode(self) -> str:
        return "manager_to_worker_observed_hash"

    @property
    def room_membership_mode(self) -> str:
        return "team_worker_members_and_matrix_convergence"


def adapter_for(manifest: AgentTeamsProfileManifest) -> AgentTeamsAdapter:
    if manifest.profile == "v1.1.2-competition":
        return LegacyAgentTeams112Adapter(manifest)
    return AgentTeams122Adapter(manifest)
