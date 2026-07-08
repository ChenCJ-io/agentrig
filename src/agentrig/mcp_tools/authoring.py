"""authoring 组 MCP 工具：构建/查询测试用例。

CC 通过这些工具操作用例库（upsert / list / get）。工具逻辑是纯函数（可单测），
register 是瘦封装，委托纯函数 + 全局 repo。
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..models import TestCase
from ..storage import get_repo
from ..storage.repo import InMemoryTestCaseRepo


async def upsert_test_case_impl(
    repo: InMemoryTestCaseRepo, case: dict[str, Any]
) -> TestCase:
    """创建/更新用例（纯函数）。"""
    tc = TestCase(**case)
    repo.upsert(tc)
    return tc


async def list_test_cases_impl(repo: InMemoryTestCaseRepo) -> list[dict[str, Any]]:
    """列出所有用例（dict 列表）。"""
    return [c.model_dump() for c in repo.list_all()]


async def get_test_case_impl(repo: InMemoryTestCaseRepo, case_id: str) -> str:
    """取单个用例 JSON；不存在返回 'not found: <id>'。"""
    c = repo.get(case_id)
    if c is None:
        return f"not found: {case_id}"
    return c.model_dump_json()


def register(mcp: FastMCP) -> None:
    """注册 authoring 工具到 FastMCP。"""

    @mcp.tool()
    async def upsert_test_case(case: dict[str, Any]) -> str:
        """创建或更新测试用例。

        case 字段：id, name, user_message, expected_tools?, mock?, tags?
        """
        tc = await upsert_test_case_impl(get_repo(), case)
        return f"upserted: {tc.id} ({tc.name})"

    @mcp.tool()
    async def list_test_cases() -> str:
        """列出所有用例（JSON 数组）。"""
        cases = await list_test_cases_impl(get_repo())
        return json.dumps(cases, ensure_ascii=False, default=str)

    @mcp.tool()
    async def get_test_case(case_id: str) -> str:
        """取单个用例（JSON）；不存在返回 not found。"""
        return await get_test_case_impl(get_repo(), case_id)
