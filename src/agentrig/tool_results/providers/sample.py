"""approved Sample 的确定性回放 Provider。"""

from __future__ import annotations

from ..matcher import exact_arguments_match
from ..models import SampleKind
from ..repository import SampleRepository
from ..schemas import SampleStep
from .base import ProviderContext, ProviderResponse, ProviderStatus


class SampleProvider:
    name = "sample"

    def __init__(self, repository: SampleRepository) -> None:
        self._repository = repository
        self._sequence_positions: dict[str, int] = {}

    async def resolve(self, context: ProviderContext) -> ProviderResponse:
        candidates = await self._repository.approved_candidates(
            context.tool_call.name,
            context.version,
        )
        for sample in candidates:
            if sample.sample_kind is SampleKind.SINGLE:
                if not exact_arguments_match(
                    sample.match_arguments,
                    context.tool_call.arguments,
                    sample.ignored_argument_paths,
                ):
                    continue
                return ProviderResponse(
                    status=ProviderStatus.HIT,
                    result=sample.content,
                    metadata={"sample_id": sample.id, "sample_kind": "single"},
                )
            steps = [SampleStep.model_validate(item) for item in sample.content]
            position = self._sequence_positions.get(sample.id, 0)
            if position >= len(steps):
                continue
            step = steps[position]
            if step.tool_name != context.tool_call.name:
                continue
            if not exact_arguments_match(
                step.match_arguments,
                context.tool_call.arguments,
                sample.ignored_argument_paths,
            ):
                continue
            self._sequence_positions[sample.id] = position + 1
            return ProviderResponse(
                status=ProviderStatus.HIT,
                result=step.result,
                metadata={
                    "sample_id": sample.id,
                    "sample_kind": "sequence",
                    "step_index": position,
                },
            )
        return ProviderResponse(
            status=ProviderStatus.MISS,
            message="no approved sample matched normalized arguments",
        )
