"""异步执行、原子结果查询和外部判定。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...evaluations.schemas import ExternalVerdictSubmit
from ...runs.schemas import RunCasesRequest
from .support import dump_model, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def check_target(
        target_id: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """检查保存 Target 的 Driver 配置、Secret 引用和可选 HTTP 连通性。"""
        return dump_model(await invoke(services.targets.check(target_id, version=version)))

    @server.tool()
    async def run_cases(value: RunCasesRequest) -> dict[str, Any]:
        """异步执行单个或批量用例并立即返回 run_id；一个 case_id 也是同一入口。"""
        return dump_model(await invoke(services.runs.run_cases(value)))

    @server.tool()
    async def get_run(run_id: str) -> dict[str, Any]:
        """读取父 Run 状态和 completed/failed/skipped/cancelled 计数。"""
        return dump_model(await invoke(services.runs.get_run(run_id)))

    @server.tool()
    async def list_case_runs(
        run_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """分页读取 Run 下每个用例×版本×重复项的原子摘要。"""
        return dump_model(
            await invoke(
                services.runs.list_case_runs(run_id, limit=limit, offset=offset)
            )
        )

    @server.tool()
    async def get_case_run(case_run_id: str) -> dict[str, Any]:
        """读取完整快照、脱敏事件和 Rule/Judge/External 各自输出。"""
        return dump_model(await invoke(services.runs.get_case_run(case_run_id)))

    @server.tool()
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """请求协作式取消；已完成和已失败的单项证据会保留。"""
        return dump_model(await invoke(services.runs.cancel_run(run_id)))

    @server.tool()
    async def submit_external_verdict(
        case_run_id: str,
        value: ExternalVerdictSubmit,
    ) -> dict[str, Any]:
        """由 Codex/Claude Code 回写当前外部结论，不修改原始证据或平台评判。"""
        return dump_model(
            await invoke(
                services.runs.submit_external_verdict(case_run_id, value)
            )
        )
