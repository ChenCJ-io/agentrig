"""种子 demo 用例（serve 启动时若仓库空则预填，便于首次体验）。

让新用户 `agentrig serve` 后立刻在前端看到可编辑/可跑的用例，而不是空列表。
"""
from __future__ import annotations

from .models import TestCase
from .storage import get_repo

SEED_CASES: list[TestCase] = [
    TestCase(
        id="tc_search_summarize",
        name="Search then summarize",
        user_message="Find recent MCP testing guidance, then summarize the key recommendations.",
        expected_tools=["search", "summarize"],
        expectations=[
            {"kind": "tool_call_order", "tools": ["search", "summarize"]},
            {"kind": "expected_tools", "tools": ["search", "summarize"]},
            {"kind": "text_contains", "needle": "recommendations"},
        ],
        mock={
            "search": {"hits": [{"title": "MCP eval guide"}], "total": 1},
            "summarize": "Key recommendations for MCP testing.",
        },
        tags=["core", "tool-flow"],
        judge_mode="rule",
    ),
    TestCase(
        id="tc_echo_demo",
        name="Echo tool (echo backend)",
        user_message="please echo this",
        expected_tools=["echo"],
        expectations=[{"kind": "expected_tools", "tools": ["echo"]}],
        mock={"echo": "echo: hi"},
        tags=["demo"],
        judge_mode="rule",
    ),
    TestCase(
        id="tc_mock_equiv",
        name="Mock equivalence match",
        user_message="search for ABC",
        expected_tools=["search"],
        expectations=[{"kind": "expected_tools", "tools": ["search"]}],
        mock={"search": {"hits": [], "total": 0}},
        tags=["mock"],
        judge_mode="rule",
    ),
    TestCase(
        id="tc_ai_rubric",
        name="AI rubric judgement",
        user_message="polite refusal path",
        expected_tools=[],
        expectations=[],
        mock={},
        rubric="agent refuses politely without hallucinating",
        tags=["ai"],
        judge_mode="ai",
    ),
]


def maybe_seed() -> None:
    """仓库空时预填种子用例。已有数据（如 SQLite 持久化）则跳过。"""
    repo = get_repo()
    if repo.list_all():
        return
    for c in SEED_CASES:
        repo.upsert(c)
