"""Mock 策略：决定一个工具调用是否 mock、返回什么。

第一周是 StaticMockPolicy（按工具名匹配）。后续 PR 接 ToolMockHub L0/L1/L2
（剧本回放、样本库、参数等价变形）。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MockPolicy(Protocol):
    """mock 策略接口（CaseRunner / Proxy 都按此注入）。"""

    def should_mock(self, tool_name: str, arguments: dict[str, Any]) -> bool: ...

    def generate(self, tool_name: str, arguments: dict[str, Any]) -> Any: ...


class StaticMockPolicy:
    """简单策略：按工具名精确匹配，返回预设结果。"""

    def __init__(self, mocks: dict[str, Any] | None = None) -> None:
        self.mocks: dict[str, Any] = mocks or {}

    def should_mock(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        return tool_name in self.mocks

    def generate(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self.mocks[tool_name]
