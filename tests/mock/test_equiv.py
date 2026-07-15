"""L1.5 等价变形 mock 测试。"""
from __future__ import annotations

from typing import Any

from agentrig.mock import EquivalenceStore, ToolMockHub


def test_equivalence_matches_case_insensitive() -> None:
    """默认归一化（小写）：大小写不同的参数等价命中。"""
    store = EquivalenceStore()
    store.add("search", {"q": "Hello"}, "result-hello")
    assert store.find("search", {"q": "hello"}) == "result-hello"
    assert store.find("search", {"q": "HELLO"}) == "result-hello"
    assert store.find("search", {"q": "world"}) is None


def test_equivalence_other_tool_not_matched() -> None:
    store = EquivalenceStore()
    store.add("search", {"q": "x"}, "r")
    assert store.find("other", {"q": "x"}) is None


def test_equivalence_nested_values_normalized() -> None:
    """嵌套 dict/list 里的字符串也归一化。"""
    store = EquivalenceStore()
    store.add("filter", {"opts": {"Name": "ABC"}}, "r1")
    assert store.find("filter", {"opts": {"Name": "abc"}}) == "r1"


def test_equivalence_custom_normalizer() -> None:
    """自定义归一化：忽略 sort 字段。"""

    def drop_sort(args: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in args.items() if k != "sort"}

    store = EquivalenceStore(normalizer=drop_sort)
    store.add("list", {"path": "/x", "sort": "asc"}, "r1")
    assert store.find("list", {"path": "/x", "sort": "desc"}) == "r1"


def test_hub_routes_l15_between_l1_and_l2() -> None:
    """hub 路由 L0 > L1 > L1.5 > L2：L1.5 命中先于 L2。"""
    hub = ToolMockHub(equiv=EquivalenceStore())
    assert hub.equiv is not None
    hub.equiv.add("search", {"q": "X"}, "equiv-result")
    hub.samples.add("search", {"q": "Y"}, "sample-result")

    # L1.5 等价命中（大小写）
    assert hub.should_mock("search", {"q": "x"}) is True
    assert hub.generate("search", {"q": "x"}) == "equiv-result"
    # L2 精确命中（无 L1.5 等价）
    assert hub.generate("search", {"q": "Y"}) == "sample-result"


def test_hub_without_equiv_skips_l15() -> None:
    """不配 equiv 时，hub 行为同原来（L0>L1>L2）。"""
    hub = ToolMockHub()
    hub.samples.add("search", {"q": "x"}, "r")
    assert hub.generate("search", {"q": "x"}) == "r"
