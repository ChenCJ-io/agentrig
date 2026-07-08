"""Trace 记录：每次工具调用留痕（mock 或真实）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEntry:
    """一次工具调用的 trace 记录。"""

    tool_name: str
    arguments: dict[str, Any]
    source: str  # "mock" | "real"
    is_error: bool = False


@dataclass
class TraceSink:
    """trace 收集器（第一周内存版；后续 PR 持久化 + 接 OTLP 出口）。"""

    entries: list[TraceEntry] = field(default_factory=list)

    def record(self, entry: TraceEntry) -> None:
        self.entries.append(entry)

    def clear(self) -> None:
        self.entries.clear()

    def by_tool(self, tool_name: str) -> list[TraceEntry]:
        """按工具名过滤（测试 + 调试用）。"""
        return [e for e in self.entries if e.tool_name == tool_name]
