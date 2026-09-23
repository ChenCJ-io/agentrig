"""普通函数适配：``fn(messages) -> str``，工具用 ``@agentrig.sdk.tool`` 标记。"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .._runtime import HarnessContext
from .._tools import as_text, registered_tools
from .base import TurnOutput


class CallableAdapter:
    """每个 CaseRun 一个进程，历史消息由适配器维护并整段传给入口函数。"""

    name = "callable"

    def __init__(self, entry: Callable[..., Any]) -> None:
        self._entry = entry
        self._messages: list[dict[str, Any]] = []

    def describe(self) -> dict[str, Any]:
        return {
            "framework": "python",
            "framework_version": None,
            "tools": [spec.to_capability() for spec in registered_tools()],
            "limitations": ["callable_tools_require_agentrig_tool_decorator"],
        }

    async def run_turn(self, message: str, context: HarnessContext) -> TurnOutput:
        del context
        self._messages.append({"role": "user", "content": message})
        value = self._entry([dict(item) for item in self._messages])
        if inspect.isawaitable(value):
            value = await value
        text, usage = _unpack(value)
        self._messages.append({"role": "assistant", "content": text})
        return TurnOutput(text=text, usage=usage)


def _unpack(value: Any) -> tuple[str, list[dict[str, Any]]]:
    usages: list[Any] = []
    if isinstance(value, dict):
        content = value.get("content", value.get("text"))
        usage = value.get("usage")
        usages = [usage] if isinstance(usage, dict) else list(usage or [])
    else:
        content = getattr(value, "content", value)
    text = "" if content is None else as_text(content)
    return text, [item for item in usages if isinstance(item, dict)]
