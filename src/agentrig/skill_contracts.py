"""Strict repository Skill contract validation used by CI and package builds."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash


class SkillCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentrig: str = Field(min_length=1)
    agentteams: list[str] = Field(min_length=1)


class SkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    role: Literal["core", "agentteams_manager", "agentteams_curator", "agentteams_judge"]
    path: str
    contract_version: str = Field(pattern=r"^agentrig\.[a-z0-9.-]+\.v[0-9]+$")
    content_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    allowed_tools: list[str]
    input_schema: str
    output_schema: str
    fixtures: list[str]
    compatible: SkillCompatibility


class SkillContractManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agentrig.skill-contract-manifest.v1"] = (
        "agentrig.skill-contract-manifest.v1"
    )
    skills: list[SkillContract] = Field(min_length=1)

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)


def validate_skill_contracts(repository_root: Path) -> SkillContractManifest:
    root = repository_root.resolve()
    manifest_path = root / "skills" / "contracts.json"
    manifest = SkillContractManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    ids = [item.id for item in manifest.skills]
    paths = [item.path for item in manifest.skills]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise ValueError("Skill contract IDs and paths must be unique")

    actual_skill_paths = {
        path.relative_to(root).as_posix()
        for path in (root / "skills").glob("**/SKILL.md")
    }
    if set(paths) != actual_skill_paths:
        raise ValueError(
            "Skill contract coverage mismatch: "
            f"missing={sorted(actual_skill_paths - set(paths))}, "
            f"unknown={sorted(set(paths) - actual_skill_paths)}"
        )
    for contract in manifest.skills:
        _validate_contract(root, contract)
    _validate_role_boundaries(manifest.skills)
    return manifest


def contracts_by_id(repository_root: Path) -> dict[str, SkillContract]:
    manifest = validate_skill_contracts(repository_root)
    return {item.id: item for item in manifest.skills}


def _validate_contract(root: Path, contract: SkillContract) -> None:
    skill_path = _safe_path(root, contract.path)
    if skill_path.name != "SKILL.md" or not skill_path.is_file():
        raise ValueError(f"Skill contract path is not a SKILL.md: {contract.path}")
    content = skill_path.read_bytes()
    actual_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if actual_hash != contract.content_sha256:
        raise ValueError(
            f"Skill content hash mismatch for {contract.id}: "
            f"expected {contract.content_sha256}, got {actual_hash}"
        )
    frontmatter_name = _frontmatter_name(content.decode("utf-8"))
    if frontmatter_name != contract.id or contract.name != contract.id:
        raise ValueError(f"Skill name mismatch for {contract.id}")
    if len(contract.allowed_tools) != len(set(contract.allowed_tools)):
        raise ValueError(f"Skill allowed_tools contains duplicates: {contract.id}")
    _validate_schema_reference(root, contract.input_schema)
    _validate_schema_reference(root, contract.output_schema)
    for fixture in contract.fixtures:
        path = _safe_path(root, fixture)
        if not path.is_file():
            raise ValueError(f"Skill fixture does not exist: {fixture}")


def _validate_schema_reference(root: Path, value: str) -> None:
    if value == "embedded:SKILL.md":
        return
    if not value.startswith("file:"):
        raise ValueError(f"unsupported Skill schema reference: {value}")
    path = _safe_path(root, value.removeprefix("file:"))
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator = validator_for(schema)
    validator.check_schema(schema)


def _validate_role_boundaries(contracts: list[SkillContract]) -> None:
    worker_tools = {
        "get_agent_invocation",
        "submit_judge_result",
        "submit_curator_result",
        "fail_agent_invocation",
    }
    manager_only = {
        "record_manager_decision",
        "create_evaluation_plan",
        "confirm_evaluation_plan",
        "submit_evaluation_plan",
    }
    for contract in contracts:
        tools = set(contract.allowed_tools)
        if contract.role == "agentteams_manager" and tools & {
            "submit_judge_result",
            "submit_curator_result",
        }:
            raise ValueError(f"Manager Skill crosses Worker result boundary: {contract.id}")
        if contract.role in {"agentteams_curator", "agentteams_judge"}:
            if tools - worker_tools:
                raise ValueError(f"Worker Skill has out-of-role tools: {contract.id}")
            if tools & manager_only:
                raise ValueError(f"Worker Skill crosses Manager boundary: {contract.id}")


def _safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"Skill contract path escapes repository: {relative}")
    return candidate


def _frontmatter_name(content: str) -> str | None:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return None
