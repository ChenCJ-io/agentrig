"""AgentTeams Manager 的最小权限 MCP 工具集。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ...assistant.models import ActorType, AssistantEventType
from ...assistant.schemas import (
    EvaluationPlanConfirm,
    EvaluationPlanCreate,
    EvaluationPlanPatch,
    EvaluationPlanSubmit,
)
from ...bootstrap import ServiceContainer
from ...cases import CaseSelector, TestCaseCreate, TestCasePatch
from ...errors import AgentRigError, ErrorCode
from ...profiles import ProfileCreate, ProfilePatch
from ...runs.models import RunEventType
from ...targets import TargetCreate, TargetPatch
from ...tool_results.models import SampleStatus
from ..tools.support import dump_model, dump_models, invoke


def register(server: FastMCP, services: ServiceContainer) -> None:
    async def require_user_confirmation(
        assistant_session_id: str,
        confirmation_event_id: str,
    ) -> None:
        event = await services.assistant.get_event(confirmation_event_id)
        if (
            event.session_id != assistant_session_id
            or event.actor_type is not ActorType.USER
            or event.event_type is not AssistantEventType.USER_MESSAGE
        ):
            raise AgentRigError(
                ErrorCode.PLAN_CONFIRMATION_REQUIRED,
                "shared asset changes require a user message from the same session",
            )

    @server.tool()
    async def get_assistant_context(assistant_session_id: str) -> dict[str, Any]:
        """恢复当前目标、活动计划和最近业务事件；大体积证据需按 run_id 查询。"""
        return await invoke(services.assistant.get_context(assistant_session_id))

    @server.tool()
    async def create_evaluation_plan(value: EvaluationPlanCreate) -> dict[str, Any]:
        """创建并预检 draft；selection 必须完整符合 V1 RunCasesRequest。"""
        safe = value.model_copy(update={"created_by": "agentteams_manager"})
        return dump_model(await invoke(services.evaluation_plans.create(safe)))

    @server.tool()
    async def update_evaluation_plan(
        evaluation_plan_id: str,
        value: EvaluationPlanPatch,
    ) -> dict[str, Any]:
        """只修改 draft；confirmed 内容冻结，调整时应创建新 revision。"""
        return dump_model(
            await invoke(services.evaluation_plans.update(evaluation_plan_id, value))
        )

    @server.tool()
    async def validate_evaluation_plan(evaluation_plan_id: str) -> dict[str, Any]:
        """使用 V1 Planner 规则只读展开用例、版本、Target、Provider 和评判器。"""
        return dump_model(
            await invoke(services.evaluation_plans.validate(evaluation_plan_id))
        )

    @server.tool()
    async def confirm_evaluation_plan(
        evaluation_plan_id: str,
        value: EvaluationPlanConfirm,
    ) -> dict[str, Any]:
        """关联同会话的真实 user_message 作为确认，Manager 不能自造授权。"""
        return dump_model(
            await invoke(services.evaluation_plans.confirm(evaluation_plan_id, value))
        )

    @server.tool()
    async def cancel_evaluation_plan(evaluation_plan_id: str) -> dict[str, Any]:
        """取消未提交计划；已提交计划应改为 cancel_run。"""
        return dump_model(await invoke(services.evaluation_plans.cancel(evaluation_plan_id)))

    @server.tool()
    async def submit_evaluation_plan(
        evaluation_plan_id: str,
        value: EvaluationPlanSubmit,
    ) -> dict[str, Any]:
        """重校验已确认计划并幂等创建 V1 Run；不提供绕过计划的 run_cases。"""
        plan, run = await invoke(
            services.evaluation_plans.submit(evaluation_plan_id, value)
        )
        return {"plan": dump_model(plan), "run": dump_model(run)}

    @server.tool()
    async def list_tags() -> list[dict[str, Any]]:
        """列出动态用例标签及使用次数。"""
        return dump_models(await invoke(services.cases.list_tags()))

    @server.tool()
    async def list_test_cases(
        selector: CaseSelector | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按能力、工具、标签和审核状态发现用例。"""
        return dump_model(
            await invoke(services.cases.list_cases(selector, limit=limit, offset=offset))
        )

    @server.tool()
    async def get_test_case(case_id: str) -> dict[str, Any]:
        """读取完整用例定义。"""
        return dump_model(await invoke(services.cases.get(case_id)))

    @server.tool()
    async def find_cases_by_tool(
        tool_names: list[str],
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """按工具名发现相关用例。"""
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
    async def create_test_case(value: TestCaseCreate) -> dict[str, Any]:
        """从脱敏证据创建 draft 用例；批准仍由人工完成。"""
        return dump_model(await invoke(services.cases.create(value)))

    @server.tool()
    async def update_test_case(case_id: str, value: TestCasePatch) -> dict[str, Any]:
        """只修改 draft/rejected 用例；approved 用例受领域层保护。"""
        return dump_model(await invoke(services.cases.update(case_id, value)))

    @server.tool()
    async def list_targets(limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """分页列出被测 Agent Target。"""
        return dump_model(
            await invoke(services.targets.list_targets(limit=limit, offset=offset))
        )

    @server.tool()
    async def get_target(target_id: str) -> dict[str, Any]:
        """读取 Target 及版本覆盖；Secret 只有 env: 引用。"""
        return dump_model(await invoke(services.targets.get(target_id)))

    @server.tool()
    async def check_target(target_id: str, version: str | None = None) -> dict[str, Any]:
        """检查 Target 连通性与 Driver 能力。"""
        return dump_model(await invoke(services.targets.check(target_id, version=version)))

    @server.tool()
    async def create_target(
        value: TargetCreate,
        assistant_session_id: str,
        confirmation_event_id: str,
    ) -> dict[str, Any]:
        """经同会话真实用户消息确认后创建 Target；模型不能提供明文密钥。"""
        await require_user_confirmation(assistant_session_id, confirmation_event_id)
        return dump_model(await invoke(services.targets.create(value)))

    @server.tool()
    async def update_target(
        target_id: str,
        value: TargetPatch,
        assistant_session_id: str,
        confirmation_event_id: str,
    ) -> dict[str, Any]:
        """经同会话真实用户消息确认后更新 Target；历史 Run 继续使用冻结快照。"""
        await require_user_confirmation(assistant_session_id, confirmation_event_id)
        return dump_model(await invoke(services.targets.update(target_id, value)))

    @server.tool()
    async def list_execution_profiles(
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """列出 Provider、评判器和超时配置。"""
        return dump_model(
            await invoke(services.profiles.list_profiles(limit=limit, offset=offset))
        )

    @server.tool()
    async def get_execution_profile(profile_id: str) -> dict[str, Any]:
        """读取一个 ExecutionProfile。"""
        return dump_model(await invoke(services.profiles.get(profile_id)))

    @server.tool()
    async def create_execution_profile(
        value: ProfileCreate,
        assistant_session_id: str,
        confirmation_event_id: str,
    ) -> dict[str, Any]:
        """经同会话真实用户消息确认后创建可复用执行方案。"""
        await require_user_confirmation(assistant_session_id, confirmation_event_id)
        return dump_model(await invoke(services.profiles.create(value)))

    @server.tool()
    async def update_execution_profile(
        profile_id: str,
        value: ProfilePatch,
        assistant_session_id: str,
        confirmation_event_id: str,
    ) -> dict[str, Any]:
        """经同会话真实用户消息确认后更新执行方案；历史 Run 不受影响。"""
        await require_user_confirmation(assistant_session_id, confirmation_event_id)
        return dump_model(await invoke(services.profiles.update(profile_id, value)))

    @server.tool()
    async def list_samples(
        status: SampleStatus | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """只读查询共享工具结果样本。"""
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
    async def get_run(run_id: str) -> dict[str, Any]:
        """读取 Run 状态和计数。"""
        return dump_model(await invoke(services.runs.get_run(run_id)))

    @server.tool()
    async def list_case_runs(
        run_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """分页读取 Run 下的原子 CaseRun。"""
        return dump_model(
            await invoke(services.runs.list_case_runs(run_id, limit=limit, offset=offset))
        )

    @server.tool()
    async def get_case_run(case_run_id: str) -> dict[str, Any]:
        """读取冻结快照、脱敏证据和独立评判结果。"""
        return dump_model(await invoke(services.runs.get_case_run(case_run_id)))

    @server.tool()
    async def list_case_run_events(
        case_run_id: str,
        event_types: list[RunEventType] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """分页读取脱敏 RunEvent；event.id 可用于 evidence_refs。"""
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
        """协作式取消已提交 Run，不删除已有证据。"""
        return dump_model(await invoke(services.runs.cancel_run(run_id)))
