"""可保存和可冻结的执行方案契约。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..infrastructure.validation import reject_plaintext_secrets
from .models import ProviderName, ToolMode


def _secret_ref(value: str | None) -> str | None:
    if value is not None and (not value.startswith("env:") or value == "env:"):
        raise ValueError("secret_ref must use env:VARIABLE_NAME")
    return value


class ModelConfigRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str
    secret_ref: str
    options: dict[str, Any] = Field(default_factory=dict)
    _validate_secret_ref = field_validator("secret_ref")(_secret_ref)
    _safe_options = field_validator("options")(
        lambda value: reject_plaintext_secrets(value, path="options")
    )


class ProviderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProviderName
    config: dict[str, Any] = Field(default_factory=dict)
    _safe_config = field_validator("config")(
        lambda value: reject_plaintext_secrets(value, path="config")
    )


class ComponentTimeouts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver: float = Field(default=120.0, gt=0)
    real_tool: float = Field(default=60.0, gt=0)
    curator: float = Field(default=30.0, gt=0)
    judge: float = Field(default=60.0, gt=0)


class ModelPricing(BaseModel):
    """One exact model price in an immutable, operator-supplied snapshot."""

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=300)
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    cached_input_per_million: Decimal | None = Field(default=None, ge=0)


class PricingSnapshot(BaseModel):
    """Prices frozen into every CaseRun profile rather than read at report time."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agentrig.pricing-snapshot.v1"] = (
        "agentrig.pricing-snapshot.v1"
    )
    source: str = Field(min_length=1, max_length=300)
    effective_at: datetime
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    rates: list[ModelPricing] = Field(min_length=1)

    @field_validator("rates")
    @classmethod
    def model_rates_are_unique(cls, value: list[ModelPricing]) -> list[ModelPricing]:
        names = [item.model for item in value]
        if len(names) != len(set(names)):
            raise ValueError("pricing snapshot cannot contain duplicate model rates")
        return value


class ExecutionProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_mode: ToolMode = ToolMode.CONTROLLED
    provider_chain: list[ProviderSpec] = Field(
        default_factory=lambda: [
            ProviderSpec(name=ProviderName.FIXTURE),
            ProviderSpec(name=ProviderName.SAMPLE),
        ]
    )
    primary_evaluator: Literal["rule", "evidence_judge", "external_controller"] | None = None
    concurrency: int = Field(default=4, ge=1)
    case_timeout_seconds: float = Field(default=300.0, gt=0)
    component_timeouts: ComponentTimeouts = Field(default_factory=ComponentTimeouts)
    repeat_count: int = Field(default=1, ge=1)
    curator_model: ModelConfigRef | None = None
    judge_model: ModelConfigRef | None = None
    pricing_snapshot: PricingSnapshot | None = None

    @field_validator("provider_chain")
    @classmethod
    def providers_are_unique(cls, value: list[ProviderSpec]) -> list[ProviderSpec]:
        names = [item.name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("provider_chain cannot contain duplicate providers")
        return value


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    config: ExecutionProfileConfig = Field(default_factory=ExecutionProfileConfig)


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    config: ExecutionProfileConfig | None = None


class ProfileView(ProfileCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class ProfilePage(BaseModel):
    items: list[ProfileView]
    total: int
    limit: int
    offset: int
