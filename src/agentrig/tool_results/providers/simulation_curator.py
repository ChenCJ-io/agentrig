"""Simulation Curator 的 Provider 适配与一次格式修正。"""

from __future__ import annotations

from pydantic import ValidationError

from ...agents.ports import SimulationCuratorPort
from ...agents.schemas import CuratorInput
from ...profiles.schemas import ModelConfigRef
from ..validator import ToolResultValidator
from .base import ProviderContext, ProviderResponse, ProviderStatus


class SimulationCuratorProvider:
    name = "simulation_curator"

    def __init__(
        self,
        curator: SimulationCuratorPort,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        validator: ToolResultValidator,
    ) -> None:
        self._curator = curator
        self._model_config = model_config
        self._timeout_seconds = timeout_seconds
        self._validator = validator

    async def resolve(self, context: ProviderContext) -> ProviderResponse:
        feedback: list[str] = []
        attempts: list[dict[str, object]] = []
        for attempt_index in range(2):
            try:
                generation = await self._curator.generate(
                    CuratorInput(
                        tool_name=context.tool_call.name,
                        arguments=context.tool_call.arguments,
                        result_schema=context.tool_call.result_schema,
                        initial_state=context.initial_state,
                        simulation_instruction=context.simulation_instruction,
                        prior_events=context.prior_events,
                        simulation_state=context.simulation_state,
                        validation_feedback=feedback,
                    ),
                    model_config=self._model_config,
                    timeout_seconds=self._timeout_seconds,
                )
            except ValidationError as exc:
                # 模型给出了合法 JSON 却不是 {result, state_updates} 外壳：与结果不合法一样纠正一次。
                feedback = [
                    "response must be one JSON object with fields result and state_updates: "
                    f"{'.'.join(str(part) for part in error['loc']) or 'response'} {error['msg']}"
                    for error in exc.errors(include_url=False)
                ]
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "candidate": None,
                        "valid": False,
                        "validation_errors": feedback,
                    }
                )
                continue
            except Exception as exc:
                return ProviderResponse(
                    status=ProviderStatus.ERROR,
                    message=f"curator model request failed: {exc}",
                    metadata={"attempts": attempts},
                )
            validation = self._validator.validate(
                generation.candidate.result,
                result_schema=context.tool_call.result_schema,
            )
            attempts.append(
                {
                    "attempt": attempt_index + 1,
                    "candidate": generation.candidate.result,
                    "valid": validation.valid,
                    "validation_errors": validation.errors,
                    "prompt_version": generation.prompt_version,
                    "model_metadata": generation.model_metadata,
                }
            )
            if validation.valid:
                context.simulation_state.update(generation.candidate.state_updates)
                return ProviderResponse(
                    status=ProviderStatus.HIT,
                    result=generation.candidate.result,
                    metadata={
                        "attempts": attempts,
                        "prompt_version": generation.prompt_version,
                        "model_metadata": generation.model_metadata,
                        "state_updates": generation.candidate.state_updates,
                    },
                )
            feedback = validation.errors
        return ProviderResponse(
            status=ProviderStatus.ERROR,
            message="curator returned an invalid result after one correction",
            metadata={"attempts": attempts},
        )
