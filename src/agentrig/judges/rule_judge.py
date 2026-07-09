"""rule 机判：基于 RoundData 的结构化规则断言（不依赖 LLM）。

支持的 expectation kind：
- expected_tools: {tools:[...]} —— 这些工具都应被调用
- text_contains: {needle:"..."} —— assistant_text 应包含 needle
- tool_call_order: {tools:[...]} —— 工具应按此顺序调用（子序列）
- not_called: {tools:[...]} —— 这些工具不应被调用

旧字段 TestCase.expected_tools 作为隐式 expected_tools expectation 处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import RoundData, TestCase


@dataclass
class Verdict:
    """机判结论。"""

    passed: bool
    reasons: list[str] = field(default_factory=list)


def judge(rd: RoundData, case: TestCase) -> Verdict:
    """按 case.expectations（及旧 expected_tools）判定，返回 Verdict。"""
    reasons: list[str] = []

    if rd.error is not None:
        reasons.append(f"error: {rd.error}")

    called = [tc.name for tc in rd.tool_calls]
    called_set = set(called)

    # 旧字段 expected_tools 作为隐式 expected_tools expectation
    if case.expected_tools:
        missing = sorted(set(case.expected_tools) - called_set)
        if missing:
            reasons.append(f"expected_tools missing: {missing}")

    for exp in case.expectations:
        kind = exp.get("kind")
        if kind == "expected_tools":
            tools: Any = exp.get("tools", [])
            missing = sorted(set(tools) - called_set)
            if missing:
                reasons.append(f"expected_tools missing: {missing}")
        elif kind == "text_contains":
            needle = str(exp.get("needle", ""))
            if needle not in rd.assistant_text:
                reasons.append(f"text_missing: {needle!r} not in assistant_text")
        elif kind == "tool_call_order":
            tools = exp.get("tools", [])
            if not _is_subsequence(tools, called):
                reasons.append(f"order_violation: {tools} not in order within {called}")
        elif kind == "not_called":
            tools = exp.get("tools", [])
            hit = sorted(set(tools) & called_set)
            if hit:
                reasons.append(f"unexpected_calls: {hit}")
        else:
            reasons.append(f"unknown_expectation_kind: {kind!r}")

    return Verdict(passed=len(reasons) == 0, reasons=reasons)


def _is_subsequence(needles: list[str], haystack: list[str]) -> bool:
    """needles 是否按顺序作为 haystack 的子序列。"""
    it = iter(haystack)
    for n in needles:
        if not any(x == n for x in it):
            return False
    return True
