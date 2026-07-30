"""Target、TargetVersion 与健康检查契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..infrastructure.validation import reject_plaintext_secrets


def _validate_secret_ref(value: str | None) -> str | None:
    if value is not None and not value.startswith("env:"):
        raise ValueError("secret_ref must use env:VARIABLE_NAME")
    if value == "env:":
        raise ValueError("secret_ref environment variable name cannot be empty")
    return value


class TargetVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    endpoint: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("options")
    @classmethod
    def options_have_no_plaintext_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        return reject_plaintext_secrets(value, path="options")


class TargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1, max_length=300)
    driver_type: str = Field(min_length=1)
    endpoint: str | None = None
    secret_ref: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    versions: list[TargetVersion] = Field(default_factory=list)

    _secret_ref = field_validator("secret_ref")(_validate_secret_ref)
    _safe_options = field_validator("options")(
        lambda value: reject_plaintext_secrets(value, path="options")
    )

    @field_validator("versions")
    @classmethod
    def versions_are_unique(cls, value: list[TargetVersion]) -> list[TargetVersion]:
        versions = [item.version for item in value]
        if len(versions) != len(set(versions)):
            raise ValueError("target versions must be unique")
        return value


class TargetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    driver_type: str | None = Field(default=None, min_length=1)
    endpoint: str | None = None
    secret_ref: str | None = None
    options: dict[str, Any] | None = None
    versions: list[TargetVersion] | None = None

    _secret_ref = field_validator("secret_ref")(_validate_secret_ref)
    _safe_options = field_validator("options")(
        lambda value: (
            reject_plaintext_secrets(value, path="options")
            if value is not None
            else value
        )
    )


class TargetView(TargetCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class TargetPage(BaseModel):
    items: list[TargetView]
    total: int
    limit: int
    offset: int


class TargetCheck(BaseModel):
    reachable: bool
    driver_type: str
    version: str | None = None
    endpoint: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    message: str
