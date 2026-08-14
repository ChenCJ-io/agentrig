"""异步执行、原子结果查询和外部判定。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from ...evaluations.schemas import ExternalVerdictSubmit
from ...runs.models import RunEventType
from ...runs.schemas import RunCasesRequest, RunCellRetryRequest
from .support import dump_model, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    @server.tool()
    async def check_target(
        target_id: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """检查 Driver 配置和 Secret，并探测 HTTP 或 ACP initialize/session 连通性。"""
        return dump_model(await invoke(services.targets.check(target_id, version=version)))

    @server.tool()
    def get_run_cases_schema() -> dict[str, Any]:
        """返回 run_cases 的完整可写 JSON Schema。"""
        return RunCasesRequest.model_json_schema()

    @server.tool()
    async def preview_run_cases(value: RunCasesRequest) -> dict[str, Any]:
        """解析稳定 Cell/Attempt Manifest；不创建 Run 或触发被测 Agent。"""
        return dump_model(await invoke(services.runs.preview_run_cases(value)))

    @server.tool()
    async def run_cases(value: RunCasesRequest) -> dict[str, Any]:
        """异步执行已预览请求；可用 expected_manifest_hash 阻止资产漂移提交。"""
        return dump_model(await invoke(services.runs.run_cases(value)))

    @server.tool()
    async def get_run(run_id: str) -> dict[str, Any]:
        """读取父 Run 调度终态和各单项计数；completed 不代表所有 CaseRun 通过。"""
        return dump_model(await invoke(services.runs.get_run(run_id)))

    @server.tool()
    async def get_run_summary(run_id: str) -> dict[str, Any]:
        """读取适合轮询的紧凑 Cell/Attempt/结论/失败分类计数。"""
        return dump_model(await invoke(services.runs.get_run_summary(run_id)))

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
    async def list_run_cells(
        run_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按稳定 Cell 分组读取 repeat Attempts 和聚合结论。"""
        return dump_model(
            await invoke(
                services.runs.list_run_cells(run_id, limit=limit, offset=offset)
            )
        )

    @server.tool()
    async def get_run_cell(run_id: str, cell_id: str) -> dict[str, Any]:
        """读取一个 Cell 的全部独立 Attempt、Timeline 与评判证据。"""
        return dump_model(await invoke(services.runs.get_run_cell(run_id, cell_id)))

    @server.tool()
    async def retry_run_cells(
        run_id: str,
        value: RunCellRetryRequest,
    ) -> dict[str, Any]:
        """从冻结 Cell 快照创建 Recovery Run；行为失败默认禁止重跑。"""
        return dump_model(await invoke(services.runs.retry_run_cells(run_id, value)))

    @server.tool()
    async def get_case_run(case_run_id: str) -> dict[str, Any]:
        """读取完整快照、脱敏事件和 Rule/Judge/External 各自输出。"""
        return dump_model(await invoke(services.runs.get_case_run(case_run_id)))

    @server.tool()
    async def list_case_run_events(
        case_run_id: str,
        event_types: list[RunEventType] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按事件类型分页读取 CaseRun 证据；返回的 event.id 可作为 evidence_refs。"""
        return dump_model(
            await invoke(
                services.runs.list_case_run_events(
                    case_run_id,
                    event_types=event_types,
                    limit=limit,
                    offset=offset,
                )
            )
        )

    @server.tool()
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """请求协作式取消；已完成和已失败的单项证据会保留。"""
        return dump_model(await invoke(services.runs.cancel_run(run_id)))

    @server.tool()
    async def submit_external_verdict(
        case_run_id: str,
        value: ExternalVerdictSubmit,
    ) -> dict[str, Any]:
        """回写外部结论；evidence_refs 只能引用 CaseRun 事件中的 event.id。"""
        return dump_model(
            await invoke(
                services.runs.submit_external_verdict(case_run_id, value)
            )
        )
