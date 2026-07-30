"""Target 与原子版本列表 CRUD。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...targets import TargetCreate, TargetPatch
from .support import dump_model, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def list_targets(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """分页列出保存的被测 Target 和版本配置。"""
        return dump_model(
            await invoke(services.targets.list_targets(limit=limit, offset=offset))
        )

    @server.tool()
    async def get_target(target_id: str) -> dict[str, Any]:
        """读取 Target、默认连接配置和 TargetVersion 覆盖列表。"""
        return dump_model(await invoke(services.targets.get(target_id)))

    @server.tool()
    async def create_target(value: TargetCreate) -> dict[str, Any]:
        """创建 Target 并在同一操作中保存版本列表；只保存 env: Secret 引用。"""
        return dump_model(await invoke(services.targets.create(value)))

    @server.tool()
    async def update_target(
        target_id: str,
        value: TargetPatch,
    ) -> dict[str, Any]:
        """修改 Target；传 versions 时原子替换完整版本列表。"""
        return dump_model(await invoke(services.targets.update(target_id, value)))

    @server.tool()
    async def delete_target(target_id: str) -> dict[str, Any]:
        """物理删除当前 Target；历史 Run 继续使用冻结快照。"""
        await invoke(services.targets.delete(target_id))
        return {"deleted": True, "target_id": target_id}
