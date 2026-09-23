"""框架适配器契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Protocol

from .._runtime import HarnessContext


@dataclass
class TurnOutput:
    """一个用户回合结束后交给 AgentRig 的最终回复与模型用量。"""

    text: str
    usage: list[dict[str, Any]] = field(default_factory=list)


class Adapter(Protocol):
    name: str

    def describe(self) -> dict[str, Any]:
        """返回 framework、framework_version、tools 与 limitations。"""
        ...

    async def run_turn(self, message: str, context: HarnessContext) -> TurnOutput: ...


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
