"""ExecutionProfile CRUD。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...profiles import ProfileCreate, ProfilePatch
from .support import dump_model, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def list_execution_profiles(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """分页列出可复用的执行方案。"""
        return dump_model(
            await invoke(
                services.profiles.list_profiles(limit=limit, offset=offset)
            )
        )

    @server.tool()
    async def get_execution_profile(profile_id: str) -> dict[str, Any]:
        """读取工具模式、Provider 顺序、评判、并发和超时配置。"""
        return dump_model(await invoke(services.profiles.get(profile_id)))

    @server.tool()
    def get_execution_profile_schema() -> dict[str, Any]:
        """返回当前 ExecutionProfile 可写 JSON Schema。"""
        return ProfileCreate.model_json_schema()

    @server.tool()
    async def create_execution_profile(value: ProfileCreate) -> dict[str, Any]:
        """创建执行方案；模型 Key 只能通过 env: Secret 引用。"""
        return dump_model(await invoke(services.profiles.create(value)))

    @server.tool()
    async def update_execution_profile(
        profile_id: str,
        value: ProfilePatch,
    ) -> dict[str, Any]:
        """修改执行方案；历史 Run 不受影响。"""
        return dump_model(await invoke(services.profiles.update(profile_id, value)))

    @server.tool()
    async def delete_execution_profile(profile_id: str) -> dict[str, Any]:
        """物理删除执行方案；历史 Run 使用自身快照。"""
        await invoke(services.profiles.delete(profile_id))
        return {"deleted": True, "profile_id": profile_id}
