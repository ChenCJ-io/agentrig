"""L1 剧本回放：按工具名顺序返回预设结果。

适合「一次用例跑中，某工具被调 N 次，每次返回不同结果」的场景
（如第一次返回成功、第二次返回错误，测 agent 的重试逻辑）。
"""
from __future__ import annotations

from typing import Any


class MockScript:
    """每个工具名一个队列，next() 顺序消费，到末尾返回 None。"""

    def __init__(self) -> None:
        self._queues: dict[str, list[Any]] = {}
        self._index: dict[str, int] = {}

    def add(self, tool_name: str, result: Any) -> None:
        """给工具追加一个顺序结果。"""
        self._queues.setdefault(tool_name, []).append(result)

    def has(self, tool_name: str) -> bool:
        """该工具是否还有未消费的剧本结果。"""
        i = self._index.get(tool_name, 0)
        return i < len(self._queues.get(tool_name, []))

    def next(self, tool_name: str) -> Any | None:
        """消费下一个剧本结果；到末尾返回 None。"""
        q = self._queues.get(tool_name, [])
        i = self._index.get(tool_name, 0)
        if i >= len(q):
            return None
        self._index[tool_name] = i + 1
        return q[i]

    def reset(self) -> None:
        """重置所有工具的消费指针（回放重新开始）。"""
        self._index.clear()
