"""按入口对象选择框架适配器；框架包只在确认需要时才导入。"""

from __future__ import annotations

from typing import Any

from .base import Adapter, TurnOutput

ADAPTER_NAMES = ("auto", "agno", "langgraph", "callable")

__all__ = ["ADAPTER_NAMES", "Adapter", "TurnOutput", "detect_adapter", "load_adapter"]


def load_adapter(target: Any, *, adapter: str = "auto") -> Adapter:
    if adapter not in ADAPTER_NAMES:
        raise ValueError(f"unsupported adapter: {adapter}")
    name = detect_adapter(target) if adapter == "auto" else adapter
    if name == "agno":
        from .agno import AgnoAdapter

        return AgnoAdapter(target)
    if name == "langgraph":
        from .langgraph import LangGraphAdapter

        return LangGraphAdapter(target)
    if name == "callable" and callable(target):
        from .callable import CallableAdapter

        return CallableAdapter(target)
    raise TypeError(
        f"unsupported entry object {type(target).__qualname__}: expected an Agno Agent/Team, "
        "a compiled LangGraph graph, or a callable(messages)"
    )


def detect_adapter(target: Any) -> str | None:
    """按类继承链识别框架，不需要先导入框架本身。"""

    for cls in type(target).__mro__:
        root = cls.__module__.split(".", 1)[0]
        if root == "agno" and cls.__name__ in {"Agent", "Team"}:
            return "agno"
        if root == "langgraph" and cls.__name__ == "Pregel":
            return "langgraph"
    return "callable" if callable(target) else None
