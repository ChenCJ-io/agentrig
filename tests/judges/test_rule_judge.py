"""rule_judge 机判测试。"""
from __future__ import annotations

from agentrig.judges import rule_judge
from agentrig.models import RoundData, TestCase, ToolCall


def _rd(
    tool_calls: list[str] | None = None,
    text: str = "",
    error: str | None = None,
) -> RoundData:
    return RoundData(
        round_number=0,
        user_message="m",
        assistant_text=text,
        tool_calls=[
            ToolCall(tool_call_id=tc, name=tc, arguments={}) for tc in (tool_calls or [])
        ],
        error=error,
    )


def test_passes_when_expected_tools_called() -> None:
    case = TestCase(id="c", name="n", user_message="m", expected_tools=["echo"])
    v = rule_judge.judge(_rd(["echo"]), case)
    assert v.passed is True
    assert v.reasons == []


def test_fails_when_expected_tool_missing() -> None:
    case = TestCase(
        id="c", name="n", user_message="m", expected_tools=["echo", "reverse"]
    )
    v = rule_judge.judge(_rd(["echo"]), case)
    assert v.passed is False
    assert any("reverse" in r for r in v.reasons)


def test_fails_on_error() -> None:
    case = TestCase(id="c", name="n", user_message="m")
    v = rule_judge.judge(_rd(error="boom"), case)
    assert v.passed is False
    assert any("error" in r for r in v.reasons)


def test_text_contains_pass_and_fail() -> None:
    case = TestCase(
        id="c", name="n", user_message="m",
        expectations=[{"kind": "text_contains", "needle": "hello"}],
    )
    assert rule_judge.judge(_rd(text="say hello"), case).passed is True
    assert rule_judge.judge(_rd(text="say hi"), case).passed is False


def test_tool_call_order() -> None:
    case = TestCase(
        id="c", name="n", user_message="m",
        expectations=[{"kind": "tool_call_order", "tools": ["a", "c"]}],
    )
    assert rule_judge.judge(_rd(["a", "b", "c"]), case).passed is True
    assert rule_judge.judge(_rd(["c", "a"]), case).passed is False


def test_not_called() -> None:
    case = TestCase(
        id="c", name="n", user_message="m",
        expectations=[{"kind": "not_called", "tools": ["danger"]}],
    )
    assert rule_judge.judge(_rd(["safe"]), case).passed is True
    assert rule_judge.judge(_rd(["danger"]), case).passed is False


def test_validator_rejects_unknown_expectation_kind() -> None:
    """TestCase 构造时拒绝未知 expectation kind（入库前校验，防脏数据）。"""
    import pytest

    with pytest.raises(Exception):  # pydantic ValidationError
        TestCase(id="c", name="n", user_message="m", expectations=[{"kind": "weird"}])


def test_empty_case_passes() -> None:
    """无 expected 无 expectations 无 error → passed=True。"""
    case = TestCase(id="c", name="n", user_message="m")
    assert rule_judge.judge(_rd(), case).passed is True
