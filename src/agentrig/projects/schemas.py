"""Strict Project, identity, environment, and release contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectScope = Literal["read", "run", "review", "ingest", "admin"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ProjectCreate(_StrictModel):
    id: str | None = None
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=300)
    default_environment: str = Field(default="development", min_length=1, max_length=128)
    redaction_policy_id: str | None = None
    retention_policy_id: str | None = None


class ProjectView(_StrictModel):
    id: str
    slug: str
    name: str
    status: Literal["active", "archived"]
    default_environment: str
    redaction_policy_id: str | None = None
    retention_policy_id: str | None = None
    created_at: datetime
    archived_at: datetime | None = None


class ProjectPage(_StrictModel):
    items: list[ProjectView]
    total: int
    limit: int
    offset: int


class EnvironmentCreate(_StrictModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    kind: Literal["development", "staging", "production", "custom"]
    release_metadata_schema: dict[str, Any] = Field(default_factory=dict)
    protected: bool = False


class EnvironmentView(EnvironmentCreate):
    id: str
    project_id: str
    created_at: datetime


class ProjectApiKeyCreate(_StrictModel):
    name: str = Field(min_length=1, max_length=300)
    scopes: list[ProjectScope] = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def scopes_are_unique(cls, value: list[ProjectScope]) -> list[ProjectScope]:
        return list(dict.fromkeys(value))


class ProjectApiKeyView(_StrictModel):
    id: str
    project_id: str
    name: str
    key_prefix: str
    scopes: list[ProjectScope]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ProjectApiKeyIssue(_StrictModel):
    api_key: ProjectApiKeyView
    token: str


class ProjectContext(_StrictModel):
    project_id: str
    principal_id: str
    scopes: list[ProjectScope]
    api_key_id: str | None = None

    def require(self, scope: ProjectScope) -> None:
        if "admin" not in self.scopes and scope not in self.scopes:
            raise PermissionError(f"project scope required: {scope}")


class ReleaseRef(_StrictModel):
    schema_version: Literal["agentrig.release-ref.v1"] = "agentrig.release-ref.v1"
    environment: str
    version: str | None = None
    git_sha: str | None = None
    build_id: str | None = None
    image_digests: dict[str, str] = Field(default_factory=dict)
    deployed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
