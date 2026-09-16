"""共享 Sample 的写入与读取契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..infrastructure.validation import reject_plaintext_secrets
from .models import SampleKind, SampleStatus


class SampleStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1)
    match_arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any


class SampleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(min_length=1, max_length=300)
    tool_name: str | None = None
    sample_kind: SampleKind = SampleKind.SINGLE
    content: Any = None
    match_arguments: dict[str, Any] = Field(default_factory=dict)
    ignored_argument_paths: list[str] = Field(default_factory=list)
    supported_versions: list[str] = Field(default_factory=list)
    source_tool_call_id: str | None = None

    @model_validator(mode="after")
    def validate_content_shape(self) -> SampleCreate:
        if self.source_tool_call_id:
            return self
        if self.sample_kind is SampleKind.SINGLE:
            if not self.tool_name:
                raise ValueError("single sample requires tool_name")
            if self.content is None:
                raise ValueError("single sample requires content")
        elif not isinstance(self.content, list) or not self.content:
            raise ValueError("sequence sample requires a non-empty content list")
        else:
            for item in self.content:
                SampleStep.model_validate(item)
        reject_plaintext_secrets(self.content, path="content")
        reject_plaintext_secrets(self.match_arguments, path="match_arguments")
        return self


class SamplePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=300)
    tool_name: str | None = None
    sample_kind: SampleKind | None = None
    content: Any = None
    match_arguments: dict[str, Any] | None = None
    ignored_argument_paths: list[str] | None = None
    supported_versions: list[str] | None = None


class SampleView(SampleCreate):
    id: str
    status: SampleStatus
    source_type: str
    created_at: datetime
    updated_at: datetime


class SamplePage(BaseModel):
    items: list[SampleView]
    total: int
    limit: int
    offset: int
