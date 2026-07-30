"""用例发现与 MCP 可写边界。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...cases import CaseSelector, TestCaseCreate, TestCasePatch
from .support import dump_model, dump_models, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def list_tags() -> list[dict[str, Any]]:
        """动态聚合用例标签及使用次数；标签无需预注册。"""
        return dump_models(await invoke(services.cases.list_tags()))

    @server.tool()
    async def list_test_cases(
        selector: CaseSelector | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按 selector 分页查询用例；字段内 OR、字段间 AND，默认排除 rejected。"""
        return dump_model(
            await invoke(
                services.cases.list_cases(selector, limit=limit, offset=offset)
            )
        )

    @server.tool()
    async def get_test_case(case_id: str) -> dict[str, Any]:
        """读取完整多轮用例、Fixture、断言、rubric 和适用版本。"""
        return dump_model(await invoke(services.cases.get(case_id)))

    @server.tool()
    async def find_cases_by_tool(
        tool_names: list[str],
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按一个或多个工具名查用例；同一工具字段内按 OR 匹配。"""
        return dump_model(
            await invoke(
                services.cases.list_cases(
                    CaseSelector(tool_names=tool_names),
                    limit=limit,
                    offset=offset,
                )
            )
        )

    @server.tool()
    def get_test_case_schema() -> dict[str, Any]:
        """返回当前 create_test_case 可写 JSON Schema。"""
        return TestCaseCreate.model_json_schema()

    @server.tool()
    async def create_test_case(value: TestCaseCreate) -> dict[str, Any]:
        """创建 draft 用例；可指定 ID，不指定则由 AgentRig 生成。"""
        return dump_model(await invoke(services.cases.create(value)))

    @server.tool()
    async def update_test_case(
        case_id: str,
        value: TestCasePatch,
    ) -> dict[str, Any]:
        """修改 draft/rejected 用例；approved 用例不可由 MCP 修改。"""
        return dump_model(await invoke(services.cases.update(case_id, value)))

    @server.tool()
    async def delete_test_case(case_id: str) -> dict[str, Any]:
        """删除 draft/rejected 用例；approved 用例不可删除。"""
        await invoke(services.cases.delete(case_id))
        return {"deleted": True, "case_id": case_id}
