"""Provider 链共享输入和结果。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ...cases.schemas import Fixture
from ...targets.drivers import ToolCall


class ProviderStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ProviderContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_run_id: str
    turn_position: int
    tool_call: ToolCall
    fixtures: list[Fixture] = Field(default_factory=list)
    version: str | None = None
    initial_state: dict[str, Any] = Field(default_factory=dict)
    simulation_instruction: str | None = None
    prior_events: list[dict[str, Any]] = Field(default_factory=list)
    simulation_state: dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ProviderStatus
    result: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class ProviderAttempt(BaseModel):
    provider: str
    status: ProviderStatus
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultProvider(Protocol):
    name: str

    async def resolve(self, context: ProviderContext) -> ProviderResponse: ...
