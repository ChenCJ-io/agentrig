"""ai 机判：用 LLMProvider 按 rubric 判 RoundData（rule_judge 的 LLM 版）。

把 rubric + RoundData 摘要组成 prompt 让 LLM 判 PASS/FAIL。比 rule_judge 灵活
（能判语义/措辞），但有 LLM 成本与不确定性；默认走 rule_judge。
"""
from __future__ import annotations

import json

from ..models import RoundData, TestCase
from ..providers.base import LLMProvider
from .rule_judge import Verdict


def _summarize_round(rd: RoundData) -> str:
    """把 RoundData 压成 LLM 可读的 JSON 摘要。"""
    calls = [{"name": tc.name, "arguments": tc.arguments} for tc in rd.tool_calls]
    return json.dumps(
        {
            "assistant_text": rd.assistant_text,
            "tool_calls": calls,
            "error": rd.error,
        },
        ensure_ascii=False,
    )


async def judge(rd: RoundData, case: TestCase, provider: LLMProvider) -> Verdict:
    """用 provider 按 case.rubric 判定；解析回答首行 PASS/FAIL。"""
    if rd.error is not None:
        return Verdict(False, [f"error: {rd.error}"])

    rubric = case.rubric or "agent 行为符合预期"
    prompt = (
        "你是测试判定器。按 rubric 判定下面的 agent 运行记录是否通过。\n"
        "rubric:\n{rubric}\n\n"
        "运行记录（JSON）:\n{record}\n\n"
        "先给一行结论（PASS 或 FAIL），再用一句话说明理由。"
    ).format(rubric=rubric, record=_summarize_round(rd))

    messages = [
        {"role": "system", "content": "你是严谨的测试判定器。"},
        {"role": "user", "content": prompt},
    ]
    answer = await provider.generate(messages)
    return _parse(answer)


def _parse(answer: str) -> Verdict:
    """解析 LLM 回答：首行 PASS/FAIL 决定 passed，整段回答作为 reason。"""
    lines = answer.strip().splitlines()
    head = lines[0].upper() if lines else ""
    passed = head.startswith("PASS")
    return Verdict(passed=passed, reasons=[answer.strip()])
