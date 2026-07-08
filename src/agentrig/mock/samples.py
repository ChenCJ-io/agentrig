"""L2 样本库：按工具名 + 参数子集匹配返回样例。

适合「按输入参数返回不同真实结果」的场景（如 read(path=/x) 返回 X，
read(path=/y) 返回 Y）。参数模式是 actual 的子集 —— pattern 里没列的字段忽略。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Sample:
    """一个样本：工具名 + 参数模式（actual 的子集）+ 结果。"""

    tool_name: str
    arguments: dict[str, Any]
    result: Any


def _matches(pattern: dict[str, Any], actual: dict[str, Any]) -> bool:
    """pattern 是 actual 的子集（pattern 每个 k:v 在 actual 里相等）。"""
    return all(actual.get(k) == v for k, v in pattern.items())


class SampleStore:
    """按工具名 + 参数子集匹配查找样例（首个命中返回）。"""

    def __init__(self, samples: list[Sample] | None = None) -> None:
        self._samples: list[Sample] = samples or []

    def add(self, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
        """追加一个样本。"""
        self._samples.append(Sample(tool_name, arguments, result))

    def find(self, tool_name: str, arguments: dict[str, Any]) -> Any | None:
        """找首个 tool_name 匹配 + 参数子集匹配的样本结果；无则 None。"""
        for s in self._samples:
            if s.tool_name == tool_name and _matches(s.arguments, arguments):
                return s.result
        return None

    def all(self) -> list[Sample]:
        """返回所有样本（调试/序列化用）。"""
        return list(self._samples)
