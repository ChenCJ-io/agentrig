"""authoring 工具纯函数测试。"""
from __future__ import annotations

from agentrig.mcp_tools.authoring import (
    get_test_case_impl,
    list_test_cases_impl,
    upsert_test_case_impl,
)
from agentrig.storage import InMemoryTestCaseRepo


async def test_upsert_and_get() -> None:
    repo = InMemoryTestCaseRepo()
    tc = await upsert_test_case_impl(
        repo, {"id": "c1", "name": "t", "user_message": "hi"}
    )
    assert tc.id == "c1"

    r = await get_test_case_impl(repo, "c1")
    assert "c1" in r
    assert "hi" in r


async def test_get_not_found() -> None:
    repo = InMemoryTestCaseRepo()
    r = await get_test_case_impl(repo, "missing")
    assert "not found" in r


async def test_list_empty_then_after_upsert() -> None:
    repo = InMemoryTestCaseRepo()
    assert await list_test_cases_impl(repo) == []

    await upsert_test_case_impl(repo, {"id": "c1", "name": "t", "user_message": "a"})
    await upsert_test_case_impl(repo, {"id": "c2", "name": "t2", "user_message": "b"})

    cases = await list_test_cases_impl(repo)
    assert {c["id"] for c in cases} == {"c1", "c2"}


async def test_upsert_with_optional_fields() -> None:
    """expected_tools / mock / tags 可选字段能正常构造。"""
    repo = InMemoryTestCaseRepo()
    tc = await upsert_test_case_impl(
        repo,
        {
            "id": "c1",
            "name": "t",
            "user_message": "hi",
            "expected_tools": ["fs__read"],
            "mock": {"fs__read": "mocked"},
            "tags": ["smoke"],
        },
    )
    assert tc.expected_tools == ["fs__read"]
    assert tc.mock == {"fs__read": "mocked"}
    assert tc.tags == ["smoke"]
