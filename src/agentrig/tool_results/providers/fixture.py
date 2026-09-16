"""用例内、有序、默认一次性消费的 Fixture Provider。"""

from __future__ import annotations

from typing import Any

from .base import ProviderContext, ProviderResponse, ProviderStatus


class FixtureProvider:
    name = "fixture"

    def __init__(self) -> None:
        self._consumed: set[tuple[int, int]] = set()

    async def resolve(self, context: ProviderContext) -> ProviderResponse:
        for index, fixture in enumerate(context.fixtures):
            key = (context.turn_position, index)
            if fixture.tool_name != context.tool_call.name:
                continue
            if key in self._consumed and not fixture.repeatable:
                continue
            if fixture.match_arguments is not None and not is_subset(
                fixture.match_arguments,
                context.tool_call.arguments,
            ):
                continue
            if not fixture.repeatable:
                self._consumed.add(key)
            return ProviderResponse(
                status=ProviderStatus.HIT,
                result=fixture.result,
                metadata={
                    "turn_position": context.turn_position,
                    "fixture_index": index,
                    "repeatable": fixture.repeatable,
                },
            )
        return ProviderResponse(
            status=ProviderStatus.MISS,
            message="no unconsumed fixture matched tool name and arguments",
        )


def is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and is_subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        return all(is_subset(left, right) for left, right in zip(expected, actual, strict=True))
    return bool(expected == actual)
