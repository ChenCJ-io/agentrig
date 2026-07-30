"""测试用例写入、查询和快照契约。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..infrastructure.validation import reject_plaintext_secrets
from .models import ReviewStatus

AssertionKind = Literal[
    "first_action",
    "tool_called",
    "tool_not_called",
    "tool_call_order",
    "tool_arguments_equal",
    "tool_arguments_schema",
    "text_contains",
    "text_regex",
    "no_execution_error",
]
PrimaryEvaluator = Literal["rule", "evidence_judge", "external_controller"]


class Assertion(BaseModel):
    """V1 的有限结构化断言，不执行脚本或表达式。"""

    model_config = ConfigDict(extra="forbid")

    kind: AssertionKind
    turn_position: int | None = Field(default=None, ge=1)
    expected_action: Literal["tool", "text", "refuse"] | None = None
    tool_name: str | None = None
    tool_names: list[str] | None = None
    expected_arguments: dict[str, Any] | None = None
    arguments_schema: dict[str, Any] | None = None
    value: str | None = None

    @model_validator(mode="after")
    def validate_kind_fields(self) -> Assertion:
        required: dict[str, tuple[str, ...]] = {
            "first_action": ("expected_action",),
            "tool_called": ("tool_name",),
            "tool_not_called": ("tool_name",),
            "tool_call_order": ("tool_names",),
            "tool_arguments_equal": ("tool_name", "expected_arguments"),
            "tool_arguments_schema": ("tool_name", "arguments_schema"),
            "text_contains": ("value",),
            "text_regex": ("value",),
            "no_execution_error": (),
        }
        missing = [name for name in required[self.kind] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} requires: {', '.join(missing)}")
        if self.kind == "tool_call_order" and not self.tool_names:
            raise ValueError("tool_call_order requires a non-empty tool_names list")
        if self.kind == "text_regex" and self.value is not None:
            try:
                re.compile(self.value)
            except re.error as exc:
                raise ValueError(f"invalid text_regex: {exc}") from exc
        return self


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    match_arguments: dict[str, Any] | None = None
    result: Any
    repeatable: bool = False


class TestTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1)
    user_message: str = Field(min_length=1)
    simulation_instruction: str | None = None
    fixtures: list[Fixture] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)
    rubric: str | None = None


class TestCaseCreate(BaseModel):
    __test__: ClassVar[bool] = False
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1, max_length=300)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    supported_versions: list[str] = Field(default_factory=list)
    primary_evaluator: PrimaryEvaluator = "rule"
    initial_state: dict[str, Any] = Field(default_factory=dict)
    case_assertions: list[Assertion] = Field(default_factory=list)
    case_rubric: str | None = None
    turns: list[TestTurn] = Field(min_length=1)

    @field_validator("tags", "supported_versions")
    @classmethod
    def unique_non_empty_strings(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            normalized = item.strip()
            if normalized and normalized not in seen:
                cleaned.append(normalized)
                seen.add(normalized)
        return cleaned

    @field_validator("initial_state")
    @classmethod
    def initial_state_has_no_plaintext_secrets(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        return reject_plaintext_secrets(value, path="initial_state")

    @field_validator("turns")
    @classmethod
    def positions_are_contiguous(cls, turns: list[TestTurn]) -> list[TestTurn]:
        positions = [turn.position for turn in turns]
        expected = list(range(1, len(turns) + 1))
        if positions != expected:
            raise ValueError(f"turn positions must be contiguous and ordered: {expected}")
        return turns

class TestCasePatch(BaseModel):
    """draft/rejected 用例的原地修改。

    Service 将 patch 合并到当前完整文档后，再用 ``TestCaseCreate`` 做同一套校验。
    """

    __test__: ClassVar[bool] = False
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    tags: list[str] | None = None
    supported_versions: list[str] | None = None
    primary_evaluator: PrimaryEvaluator | None = None
    initial_state: dict[str, Any] | None = None
    case_assertions: list[Assertion] | None = None
    case_rubric: str | None = None
    turns: list[TestTurn] | None = None


class TestCaseView(TestCaseCreate):
    __test__: ClassVar[bool] = False
    id: str
    review_status: ReviewStatus
    created_at: datetime
    updated_at: datetime


class CaseSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    review_status: list[ReviewStatus] = Field(default_factory=list)


class TestCasePage(BaseModel):
    items: list[TestCaseView]
    total: int
    limit: int
    offset: int


class TagUsage(BaseModel):
    tag: str
    count: int
