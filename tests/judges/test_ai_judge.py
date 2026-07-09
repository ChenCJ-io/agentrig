"""ai_judge 测试（注入 fake provider，不发真实请求）。"""
from __future__ import annotations

from agentrig.judges import ai_judge
from agentrig.models import RoundData, TestCase


class _FakeProvider:
    """实现 LLMProvider Protocol，返回固定回答。"""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.called = False

    async def generate(
        self, messages: list[dict[str, str]], *, model: str | None = None
    ) -> str:
        self.called = True
        return self.answer


async def test_ai_passes_on_pass_answer() -> None:
    rd = RoundData(round_number=0, user_message="m", assistant_text="ok")
    case = TestCase(id="c", name="n", user_message="m", rubric="should be fine")
    fake = _FakeProvider("PASS looks good")
    v = await ai_judge.judge(rd, case, fake)
    assert v.passed is True
    assert fake.called is True


async def test_ai_fails_on_fail_answer() -> None:
    rd = RoundData(round_number=0, user_message="m", assistant_text="bad")
    case = TestCase(id="c", name="n", user_message="m", rubric="should be fine")
    v = await ai_judge.judge(rd, case, _FakeProvider("FAIL tool not called"))
    assert v.passed is False


async def test_ai_short_circuits_on_error_without_calling_provider() -> None:
    """rd 有 error 时直接判失败，不调 provider。"""
    rd = RoundData(round_number=0, user_message="m", error="boom")
    case = TestCase(id="c", name="n", user_message="m")
    fake = _FakeProvider("PASS")  # 不应被调
    v = await ai_judge.judge(rd, case, fake)
    assert v.passed is False
    assert any("error" in r for r in v.reasons)
    assert fake.called is False
