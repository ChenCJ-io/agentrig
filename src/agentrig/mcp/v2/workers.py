"""Curator/Judge Worker 的角色隔离结果回写工具。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...agents.invocation_models import AgentRole
from ...agents.invocation_schemas import AgentInvocationFailure, AgentResultSubmit
from ...agents.schemas import CuratorGeneration, JudgeOutput
from ...bootstrap import ServiceContainer
from ..tools.support import dump_model, invoke


def register_curator(server: FastMCP, services: ServiceContainer) -> None:
    role = AgentRole.SIMULATION_CURATOR

    @server.tool()
    async def get_agent_invocation(invocation_id: str) -> dict[str, Any]:
        """领取指定 Curator 任务并读取已脱敏的冻结输入；不支持任务列表。"""
        return dump_model(
            await invoke(
                services.agent_invocations.claim(
                    invocation_id,
                    role=role,
                    assigned_agent="agentteams_curator",
                )
            )
        )

    @server.tool()
    async def submit_curator_result(
        invocation_id: str,
        result: CuratorGeneration,
        idempotency_key: str,
        response_event_id: str | None = None,
    ) -> dict[str, Any]:
        """幂等提交 CuratorCandidate；后端仍会执行统一 ToolResultValidator。"""
        return dump_model(
            await invoke(
                services.agent_invocations.submit_result(
                    invocation_id,
                    AgentResultSubmit(
                        idempotency_key=idempotency_key,
                        result=result.model_dump(mode="json"),
                        response_event_id=response_event_id,
                    ),
                    role=role,
                )
            )
        )

    _register_failure(server, services, role)


def register_judge(server: FastMCP, services: ServiceContainer) -> None:
    role = AgentRole.EVIDENCE_JUDGE

    @server.tool()
    async def get_agent_invocation(invocation_id: str) -> dict[str, Any]:
        """领取指定 Judge 任务并读取冻结 rubric、Rule 结果和脱敏证据。"""
        return dump_model(
            await invoke(
                services.agent_invocations.claim(
                    invocation_id,
                    role=role,
                    assigned_agent="agentteams_judge",
                )
            )
        )

    @server.tool()
    async def submit_judge_result(
        invocation_id: str,
        result: JudgeOutput,
        idempotency_key: str,
        response_event_id: str | None = None,
    ) -> dict[str, Any]:
        """幂等提交引用真实 event.id 的 JudgeOutput。"""
        return dump_model(
            await invoke(
                services.agent_invocations.submit_result(
                    invocation_id,
                    AgentResultSubmit(
                        idempotency_key=idempotency_key,
                        result=result.model_dump(mode="json"),
                        response_event_id=response_event_id,
                    ),
                    role=role,
                )
            )
        )

    _register_failure(server, services, role)


def _register_failure(
    server: FastMCP,
    services: ServiceContainer,
    role: AgentRole,
) -> None:
    @server.tool(name="fail_agent_invocation")
    async def fail_agent_invocation(
        invocation_id: str,
        error_code: str,
        message: str,
        retryable: bool = False,
        response_event_id: str | None = None,
    ) -> dict[str, Any]:
        """以结构化错误结束当前角色的任务，终态不可回退。"""
        return dump_model(
            await invoke(
                services.agent_invocations.fail(
                    invocation_id,
                    AgentInvocationFailure(
                        error_code=error_code,
                        error_message=message,
                        retryable=retryable,
                        response_event_id=response_event_id,
                    ),
                    role=role,
                )
            )
        )
