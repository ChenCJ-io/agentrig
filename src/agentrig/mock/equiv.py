"""L1.5 等价变形：参数归一化后匹配样本。

适合「参数存在等价变形」的场景：大小写不同、字段顺序不同、多余字段等
（如 search(q="AbC") 与 search(q="abc") 等价）。默认归一化递归把字符串值
小写；可传自定义 normalizer（接收原始 arguments dict，返回归一化 dict）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Normalizer = Callable[[dict[str, Any]], dict[str, Any]]


def default_normalize(arguments: dict[str, Any]) -> dict[str, Any]:
    """默认归一化：递归把所有字符串值小写。"""
    return {k: _normalize_value(v) for k, v in arguments.items()}


def _normalize_value(v: Any) -> Any:
    if isinstance(v, str):
        return v.lower()
    if isinstance(v, dict):
        return {k: _normalize_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_normalize_value(x) for x in v]
    return v


@dataclass
class EquivSample:
    """一个等价样本：工具名 + 参数 + 结果（匹配时按归一化参数相等）。"""

    tool_name: str
    arguments: dict[str, Any]
    result: Any


class EquivalenceStore:
    """按归一化后的参数相等匹配样本（首个命中返回）。"""

    def __init__(self, normalizer: Normalizer | None = None) -> None:
        self._samples: list[EquivSample] = []
        self._normalize = normalizer or default_normalize

    def add(self, tool_name: str, arguments: dict[str, Any], result: Any) -> None:
        """追加一个等价样本。"""
        self._samples.append(EquivSample(tool_name, arguments, result))

    def find(self, tool_name: str, arguments: dict[str, Any]) -> Any | None:
        """按工具名 + 归一化参数相等找首个样本结果；无则 None。"""
        norm_actual = self._normalize(arguments)
        for s in self._samples:
            if s.tool_name == tool_name and self._normalize(s.arguments) == norm_actual:
                return s.result
        return None

    def all(self) -> list[EquivSample]:
        """返回所有样本（调试/序列化用）。"""
        return list(self._samples)
