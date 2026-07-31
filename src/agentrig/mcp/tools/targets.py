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
    def list_driver_types() -> list[dict[str, Any]]:
        """列出当前部署支持的 Driver、能力和部署就绪状态；不暴露 allowlist 路径。"""
        return services.targets.list_driver_types()

    @server.tool()
    def get_target_schema(driver_type: str | None = None) -> dict[str, Any]:
        """返回 Target 写入 Schema；传 driver_type 时同时返回其 options Schema。"""
        return services.targets.schema(driver_type)

    @server.tool()
    async def create_target(value: TargetCreate) -> dict[str, Any]:
        """创建已通过当前部署预检的 Target；只保存 env: Secret 引用。"""
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
