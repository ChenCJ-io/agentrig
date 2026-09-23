"""仓库内项目文件的契约（AR-RFC-0006）。

用例文件直接复用 :class:`agentrig.cases.TestCaseCreate`，这里只定义 ``project.yaml``。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..infrastructure.validation import reject_plaintext_secrets

LocalProvider = Literal["fixture", "sample", "simulation_curator"]
_SECRET_REF = r"^env:[A-Za-z_][A-Za-z0-9_]*$"


class ProjectTarget(BaseModel):
    """被测 Agent；相对路径以项目文件里的 ``root`` 为基准。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="agent", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    entry: str = Field(min_length=3)
    python: str | None = Field(
        default=None,
        description="被测项目的解释器；不填时使用运行 agentrig 的解释器。",
    )
    cwd: str = "."
    adapter: Literal["auto", "agno", "langgraph", "callable"] = "auto"
    factory: bool = False
    secret: str | None = Field(default=None, pattern=_SECRET_REF)
    credential_env: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    inherit_env: list[str] = Field(default_factory=list)
    startup_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    version: str = Field(default="local", min_length=1, max_length=300)

    _safe_env = field_validator("env")(
        lambda value: reject_plaintext_secrets(value, path="target.env")
    )


class ProjectModel(BaseModel):
    """Curator 或 Judge 使用的 OpenAI 兼容模型。"""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    secret: str = Field(pattern=_SECRET_REF)
    options: dict[str, Any] = Field(default_factory=dict)


def _default_providers() -> list[LocalProvider]:
    # 2026-09-23 确认：Fixture 未命中时默认由 Curator 模拟。
    return ["fixture", "sample", "simulation_curator"]


class ProjectProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[LocalProvider] = Field(default_factory=_default_providers, min_length=1)
    curator: ProjectModel | None = None
    judge: ProjectModel | None = None
    concurrency: int = Field(default=4, ge=1, le=64)
    repeat: int = Field(default=1, ge=1, le=20)
    case_timeout_seconds: float = Field(default=600.0, gt=0)

    @field_validator("providers")
    @classmethod
    def providers_are_unique(cls, value: list[LocalProvider]) -> list[LocalProvider]:
        if len(value) != len(set(value)):
            raise ValueError("profile.providers cannot contain duplicates")
        return value


class ProjectFile(BaseModel):
    """``agentrig/project.yaml``。"""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    root: str = Field(
        default="..",
        description="相对路径的基准目录，相对项目文件所在目录；默认是 agentrig/ 的上一级。",
    )
    cases: str = Field(default="cases", description="用例目录，相对项目文件所在目录。")
    target: ProjectTarget
    initial_state: dict[str, Any] = Field(default_factory=dict)
    profile: ProjectProfile = Field(default_factory=ProjectProfile)

    _safe_state = field_validator("initial_state")(
        lambda value: reject_plaintext_secrets(value, path="initial_state")
    )
