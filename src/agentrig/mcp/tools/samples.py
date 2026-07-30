"""Sample 草稿 CRUD；审核不暴露给 MCP。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...tool_results import SampleCreate, SamplePatch
from ...tool_results.models import SampleStatus
from .support import dump_model, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def list_samples(
        status: SampleStatus | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """分页查询共享工具结果；只有 approved 样本会被 Provider 命中。"""
        return dump_model(
            await invoke(
                services.samples.list_samples(
                    status=status,
                    tool_name=tool_name,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    @server.tool()
    async def get_sample(sample_id: str) -> dict[str, Any]:
        """读取单次或有序序列 Sample 的匹配内容和状态。"""
        return dump_model(await invoke(services.samples.get(sample_id)))

    @server.tool()
    async def create_sample(value: SampleCreate) -> dict[str, Any]:
        """直接创建草稿，或用 Real Tool 的 source_tool_call_id 显式创建草稿。"""
        return dump_model(await invoke(services.samples.create(value)))

    @server.tool()
    async def update_sample(
        sample_id: str,
        value: SamplePatch,
    ) -> dict[str, Any]:
        """只允许修改 draft Sample；approved/disabled 不可由 MCP 修改。"""
        return dump_model(await invoke(services.samples.update(sample_id, value)))

    @server.tool()
    async def delete_sample(sample_id: str) -> dict[str, Any]:
        """只允许删除 draft Sample。"""
        await invoke(services.samples.delete(sample_id))
        return {"deleted": True, "sample_id": sample_id}
