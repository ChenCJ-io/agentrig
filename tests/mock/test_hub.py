"""ToolMockHub 单元测试：L0/L1/L2 路由 + 优先级 + 边界。"""
from __future__ import annotations

from agentrig.mock import SampleStore, ToolMockHub


def test_l0_inline_highest_priority() -> None:
    """L0 内联压过 L1 剧本和 L2 样本库。"""
    hub = ToolMockHub()
    hub.set_inline("fs__read", "inline-result")
    hub.script.add("fs__read", "script-result")  # L1 也有，但 L0 优先

    assert hub.should_mock("fs__read", {})
    assert hub.generate("fs__read", {}) == "inline-result"


def test_l1_script_sequential_consumption() -> None:
    """L1 剧本按顺序消费，到末尾 has 返回 False。"""
    hub = ToolMockHub()
    hub.script.add("fs__read", "first")
    hub.script.add("fs__read", "second")

    assert hub.generate("fs__read", {}) == "first"
    assert hub.generate("fs__read", {}) == "second"
    assert not hub.script.has("fs__read")
    assert not hub.should_mock("fs__read", {})


def test_l2_sample_match_by_argument_subset() -> None:
    """L2 按工具名 + 参数子集匹配；pattern 没列的字段忽略。"""
    samples = SampleStore()
    samples.add("fs__read", {"path": "/x"}, "content-x")
    samples.add("fs__read", {"path": "/y"}, "content-y")
    hub = ToolMockHub(samples=samples)

    # extra 字段不影响匹配
    assert hub.generate("fs__read", {"path": "/x", "extra": "ignored"}) == "content-x"
    assert hub.generate("fs__read", {"path": "/y"}) == "content-y"
    # 无匹配
    assert not hub.should_mock("fs__read", {"path": "/z"})


def test_l0_l1_l2_priority_order() -> None:
    """三层都在时，L0 > L1 > L2；L0 清掉后 L1，L1 到末尾后 L2。"""
    samples = SampleStore()
    samples.add("tool", {}, "l2-result")
    hub = ToolMockHub(samples=samples)
    hub.script.add("tool", "l1-result")
    hub.set_inline("tool", "l0-result")

    assert hub.generate("tool", {}) == "l0-result"
    hub.clear_inline()
    assert hub.generate("tool", {}) == "l1-result"
    # L1 到末尾后，落到 L2
    assert hub.generate("tool", {}) == "l2-result"


def test_no_mock_returns_false() -> None:
    """三层都无 mock 时 should_mock 返回 False。"""
    hub = ToolMockHub()
    assert not hub.should_mock("any__tool", {})


def test_script_reset_replays() -> None:
    """reset 后剧本可重新回放。"""
    hub = ToolMockHub()
    hub.script.add("t", "a")
    hub.script.add("t", "b")
    assert hub.generate("t", {}) == "a"
    assert hub.generate("t", {}) == "b"

    hub.script.reset()
    assert hub.generate("t", {}) == "a"
