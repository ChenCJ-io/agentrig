from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from scripts.build_agentteams_packages import ROLES, build

from agentrig.integrations.agentteams import (
    AgentTeamsInvocationEvidence,
    AgentTeamsMembershipEvidence,
    AgentTeamsProfileManifest,
    AgentTeamsSkillEvidence,
    adapter_for,
)
from agentrig.skill_contracts import validate_skill_contracts

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "deploy" / "agentteams" / "profiles"


def _manifest(name: str) -> AgentTeamsProfileManifest:
    return AgentTeamsProfileManifest.model_validate_json(
        (PROFILE_ROOT / name / "manifest.json").read_text(encoding="utf-8")
    )


def test_agentteams_profiles_keep_legacy_read_only_and_pin_current_digests() -> None:
    legacy = _manifest("v1.1.2-competition")
    current = _manifest("v1.2.2-current")
    assert legacy.historical_read_only is True
    legacy_resource = ROOT / "deploy" / "agentteams" / "resources-v1.1.2.yaml"
    assert (
        f"sha256:{hashlib.sha256(legacy_resource.read_bytes()).hexdigest()}"
        == legacy.resource_schema_hash
    )
    assert current.historical_read_only is False
    assert current.agentteams_version == "v1.2.2"
    assert current.runtime_name == "qwenpaw"
    assert all(
        "@sha256:" in value
        for value in [current.controller_image, *current.runtime_images.values()]
    )
    bad = current.model_copy(update={"controller_image": "registry/controller:v1.2.2"})
    with pytest.raises(ValidationError, match="immutable multi-arch image digests"):
        AgentTeamsProfileManifest.model_validate(bad.model_dump())


def test_v122_resources_validate_roles_routes_team_membership_and_schema_hash() -> None:
    manifest = _manifest("v1.2.2-current")
    schema_path = PROFILE_ROOT / "v1.2.2-current" / "resource-schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert (
        f"sha256:{hashlib.sha256(schema_path.read_bytes()).hexdigest()}"
        == manifest.resource_schema_hash
    )
    resources = list(
        yaml.safe_load_all(
            (PROFILE_ROOT / "v1.2.2-current" / "resources.yaml").read_text(
                encoding="utf-8"
            )
        )
    )
    adapter_for(manifest).validate_resources(resources, schema)
    workers = {
        item["metadata"]["name"]: item for item in resources if item["kind"] == "Worker"
    }
    assert set(workers) == {"agentrig-manager", "agentrig-curator", "agentrig-judge"}
    for role in ("manager", "curator", "judge"):
        worker = workers[f"agentrig-{role}"]
        assert worker["spec"]["package"].endswith(f"agentrig-{role}.zip")
        [route] = worker["spec"]["mcpServers"]
        assert route["name"] == f"agentrig-{role}"
        assert route["url"].endswith(f"/agentrig-{role}/mcp")
    team = next(item for item in resources if item["kind"] == "Team")
    members = team["spec"]["workerMembers"]
    assert [item["name"] for item in members] == [
        "agentrig-manager",
        "agentrig-curator",
        "agentrig-judge",
    ]
    assert sum(item["role"] == "team_leader" for item in members) == 1


def test_v122_packages_and_both_compat_reports_are_version_isolated(tmp_path: Path) -> None:
    skill_manifest = validate_skill_contracts(ROOT)
    contracts = {item.id: item for item in skill_manifest.skills}
    built = build(ROOT, tmp_path, profile="v1.2.2-current")
    for package in built:
        role = package.stem.removeprefix("agentrig-")
        with ZipFile(package) as archive:
            contract = json.loads(archive.read("manifest.json"))["agentrig_contract"]
        assert contract == {
            "schema_version": "agentrig.agentteams-package.v1",
            "profile": "v1.2.2-current",
            "agentteams_version": "v1.2.2",
            "role": role,
            "skill_contract_manifest_hash": skill_manifest.content_hash,
            "skills": [
                {
                    "id": skill_name,
                    "contract_version": contracts[skill_name].contract_version,
                    "content_sha256": contracts[skill_name].content_sha256,
                }
                for skill_name in ROLES[role]
            ],
        }

    observed_at = datetime(2026, 8, 10, tzinfo=timezone.utc)
    legacy_manifest = _manifest("v1.1.2-competition")
    legacy = adapter_for(legacy_manifest).capability_report(
        runtime_observation={
            "version": "v1.1.2",
            "runtime_version": "openclaw-v1.1.2",
            "resource_api_version": "hiclaw.io/v1beta1",
            "transport_health": "healthy",
        },
        invocations=[
            AgentTeamsInvocationEvidence(
                invocation_id="legacy-canary",
                role="judge",
                assigned_agent="agentrig-judge",
                terminal_status="completed",
                correlation_verified=True,
            )
        ],
        observed_at=observed_at,
    )
    assert legacy.profile == "v1.1.2-competition"
    assert legacy.failures == []

    current_manifest = _manifest("v1.2.2-current")
    skills = [
        AgentTeamsSkillEvidence(
            role=role,  # type: ignore[arg-type]
            skill_id=skill,
            contract_version="1.0",
            local_package_hash=f"sha256:{role}-{skill}",
            assigned=True,
            observed_package_hash=f"sha256:{role}-{skill}",
            enabled=True,
            canary_succeeded=True,
        )
        for role, names in ROLES.items()
        for skill in names
    ]
    memberships = [
        AgentTeamsMembershipEvidence(
            room_id_hash="sha256:room",
            expected_members=["manager", "curator", "judge"],
            observed_members=["judge", "manager", "curator", "judge"],
            private_room_verified=True,
        )
    ]
    invocations = [
        AgentTeamsInvocationEvidence(
            invocation_id=f"current-{role}",
            role=role,
            assigned_agent=f"agentrig-{role}",
            terminal_status="completed",
            correlation_verified=True,
        )
        for role in ("manager", "curator", "judge")
    ]
    observation = {
        "version": "v1.2.2",
        "runtime_version": "qwenpaw-v1.2.2",
        "resource_api_version": "agentteams.io/v1beta1",
        "transport_health": "healthy",
    }
    current_adapter = adapter_for(current_manifest)
    current = current_adapter.capability_report(
        runtime_observation=observation,
        skills=skills,
        memberships=memberships,
        invocations=invocations,
        observed_at=observed_at,
    )
    repeated = current_adapter.capability_report(
        runtime_observation=observation,
        skills=skills,
        memberships=memberships,
        invocations=invocations,
        observed_at=observed_at,
    )
    assert current.profile == "v1.2.2-current"
    assert current.failures == []
    assert current.source_snapshot_hash == repeated.source_snapshot_hash
    assert current.result_hash == repeated.result_hash
    assert current.source_snapshot_hash != legacy.source_snapshot_hash

    drift = skills[0].model_copy(update={"observed_package_hash": "sha256:drift"})
    failed = current_adapter.capability_report(
        runtime_observation=observation,
        skills=[drift, *skills[1:]],
        memberships=memberships,
        invocations=invocations,
        observed_at=observed_at,
    )
    assert any(item.startswith("skill_drift:") for item in failed.failures)
