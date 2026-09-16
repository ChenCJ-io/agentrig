"""Wire models accepted by the public reference target."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReferenceScenario = Literal[
    "reference_success",
    "reference_policy_regression",
    "reference_recovery",
]
ReferenceVersion = Literal["baseline", "candidate-regression"]
RequestType = Literal["chat", "tool_result"]


class ReferenceScenarioConfig(BaseModel):
    """Scenario selector injected through a TestCase ``initial_state``."""

    model_config = ConfigDict(extra="forbid")

    scenario: ReferenceScenario = "reference_success"
    attempt: int = Field(default=1, ge=1)


class ToolResultInput(BaseModel):
    """One tool result sent back by AgentRig's fixture provider."""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    result: str
    status: Literal["success", "error"] = "success"


class ChatStreamRequest(BaseModel):
    """Subset of the AgentRig HTTP/SSE driver protocol used by the target."""

    model_config = ConfigDict(extra="forbid")

    type: RequestType
    message: str | None = None
    session_id: str | None = None
    version: ReferenceVersion | None = None
    initial_state: dict[str, Any] = Field(default_factory=dict)
    tool_proxy: dict[str, Any] | None = None
    tool_results: list[ToolResultInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request_shape(self) -> "ChatStreamRequest":
        if self.type == "chat" and not self.message:
            raise ValueError("chat requests require message")
        if self.type == "tool_result":
            if not self.session_id:
                raise ValueError("tool_result requests require session_id")
            if not self.tool_results:
                raise ValueError("tool_result requests require tool_results")
            if len(self.tool_results) != 1:
                raise ValueError("tool_result requests require exactly one result")
        if self.type == "chat" and not self.session_id:
            self.reference_config()
        return self

    def reference_config(self) -> ReferenceScenarioConfig:
        """Resolve and validate the scenario configuration."""

        raw_config = self.initial_state.get("reference", {})
        return ReferenceScenarioConfig.model_validate(raw_config)
