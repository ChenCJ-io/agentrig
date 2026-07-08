"""execution 工具 run_single_case 测试。"""
from __future__ import annotations

from agentrig.mcp_tools.execution import run_single_case_impl
from agentrig.models import TestCase
from agentrig.storage import InMemoryTestCaseRepo


async def test_run_not_found() -> None:
    repo = InMemoryTestCaseRepo()
    r = await run_single_case_impl(repo, "missing")
    assert r["error"] == "not found: missing"


async def test_run_with_mock_passes() -> None:
    """case 有 mock + expected_tools，agent 调 mock 工具，passed=True。"""
    repo = InMemoryTestCaseRepo()
    repo.upsert(
        TestCase(
            id="c1",
            name="t",
            user_message="read a file",
            expected_tools=["fs__read"],
            mock={"fs__read": "file-content"},
        )
    )
    r = await run_single_case_impl(repo, "c1")
    assert r["passed"] is True
    assert r["tool_calls"] == ["fs__read"]
    assert r["missing_expected_tools"] == []
    assert r["error"] is None


async def test_run_missing_expected_tool_fails() -> None:
    """mock 只覆盖部分 expected_tools，未覆盖的进 missing，passed=False。"""
    repo = InMemoryTestCaseRepo()
    repo.upsert(
        TestCase(
            id="c1",
            name="t",
            user_message="hi",
            expected_tools=["fs__read", "fs__write"],
            mock={"fs__read": "content"},  # 只 mock read，agent 只调 read
        )
    )
    r = await run_single_case_impl(repo, "c1")
    assert r["passed"] is False
    assert "fs__write" in r["missing_expected_tools"]
    assert "fs__read" not in r["missing_expected_tools"]


async def test_run_no_tools_no_expected_passes() -> None:
    """无 mock 无 expected：agent 不调工具，passed=True（空也过）。"""
    repo = InMemoryTestCaseRepo()
    repo.upsert(TestCase(id="c1", name="t", user_message="hi"))
    r = await run_single_case_impl(repo, "c1")
    assert r["passed"] is True
    assert r["tool_calls"] == []
