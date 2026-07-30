"""Simulation Curator 与 Evidence Judge 的独立 I/O Schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CuratorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any]
    result_schema: dict[str, Any] | None = None
    initial_state: dict[str, Any] = Field(default_factory=dict)
    simulation_instruction: str | None = None
    prior_events: list[dict[str, Any]] = Field(default_factory=list)
    simulation_state: dict[str, Any] = Field(default_factory=dict)
    validation_feedback: list[str] = Field(default_factory=list)


class CuratorCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Any
    state_updates: dict[str, Any] = Field(default_factory=dict)


class CuratorGeneration(BaseModel):
    candidate: CuratorCandidate
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str


class JudgeCriterionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    verdict: Literal["pass", "fail", "inconclusive"]
    evidence_refs: list[str] = Field(default_factory=list)


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail", "inconclusive"]
    summary: str
    criteria: list[JudgeCriterionOutput] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
