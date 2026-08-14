"""不依赖 AgentTeams、但仍由真实模型驱动的基础评测助手。"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from ..agents import ModelClient
from ..cases import CaseSelector, CaseService
from ..config import BasicAssistantProviderConfig
from ..errors import AgentRigError, ErrorCode
from ..infrastructure.secrets import SecretResolver
from ..profiles import ProfileService
from ..runs.service import RunService
from ..targets import TargetService
from .models import ActorType, AssistantEventType, AssistantTurnStatus, DeliveryStatus
from .plan_service import EvaluationPlanService
from .schemas import (
    AssistantEventView,
    AssistantProviderHealth,
    BasicAssistantOutput,
    EvaluationPlanConfirm,
    EvaluationPlanCreate,
    EvaluationPlanSubmit,
)
from .service import AssistantService

_ACTOR_ID = "agentrig-basic-assistant"


class BasicAssistantRuntime:
    def __init__(
        self,
        *,
        config: BasicAssistantProviderConfig,
        model_client: ModelClient,
        secrets: SecretResolver,
        assistant: AssistantService,
        plans: EvaluationPlanService,
        cases: CaseService,
        targets: TargetService,
        profiles: ProfileService,
        runs: RunService,
    ) -> None:
        self._config = config
        self._model_client = model_client
        self._secrets = secrets
        self._assistant = assistant
        self._plans = plans
        self._cases = cases
        self._targets = targets
        self._profiles = profiles
        self._runs = runs

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def health(self) -> AssistantProviderHealth:
        if not self.enabled:
            return AssistantProviderHealth(
                enabled=False,
                available=False,
                provider="none",
                message="未配置基础智能助手模型",
            )
        try:
            available = self._secrets.resolve(self._config.secret_ref) is not None
        except Exception:
            available = False
        return AssistantProviderHealth(
            enabled=True,
            available=available,
            provider="openai_compatible",
            message=(
                "基础智能助手已就绪"
                if available
                else "基础智能助手密钥环境变量不可用"
            ),
        )

    async def process(self, event_id: str, turn_id: str) -> None:
        await self._assistant.set_turn_status(turn_id, AssistantTurnStatus.RUNNING)
        try:
            event = await self._assistant.get_event(event_id)
            await self._assistant.set_event_delivery(event_id, DeliveryStatus.LOCAL)
            action = event.payload.get("plan_action")
            if isinstance(action, dict) and action.get("action_type"):
                metadata = await self._handle_plan_action(event, action)
            else:
                metadata = await self._handle_model_turn(event, turn_id)
            await self._assistant.set_turn_status(
                turn_id,
                AssistantTurnStatus.COMPLETED,
                model_metadata=metadata,
            )
        except Exception as exc:
            code = (
                exc.detail.code.value
                if isinstance(exc, AgentRigError)
                else ErrorCode.INTERNAL_ERROR.value
            )
            event = await self._assistant.get_event(event_id)
            await self._assistant.append_event(
                event.session_id,
                AssistantEventType.ERROR,
                actor_type=ActorType.SYSTEM,
                actor_id="agentrig",
                payload={"message": _public_error(exc), "code": code},
                turn_id=turn_id,
            )
            await self._assistant.set_event_delivery(
                event_id,
                DeliveryStatus.FAILED,
                last_error=_public_error(exc),
            )
            await self._assistant.set_turn_status(
                turn_id,
                AssistantTurnStatus.FAILED,
                error_code=code,
                error_message=_public_error(exc),
            )

    async def _handle_model_turn(
        self,
        event: AssistantEventView,
        turn_id: str,
    ) -> dict[str, object]:
        session_id = event.session_id
        session = await self._assistant.get_session(session_id)
        context = await self._compact_context(session_id)
        api_key = self._secrets.resolve(self._config.secret_ref)
        if api_key is None:
            raise AgentRigError(
                ErrorCode.ASSISTANT_PROVIDER_UNAVAILABLE,
                "基础智能助手密钥未配置",
            )
        user_content = str(event.payload.get("content") or "")
        output = await self._model_client.generate_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 AgentRig 基础智能评测助手。普通问题直接自然回答；只有用户明确要求"
                        "执行或比较评测时才返回 create_plan。不要输出内部推理、工具旁白或英文进度。"
                        "只使用给定资产 ID，不得编造 Target、Case、Profile、Run 或结论。"
                        "create_plan.selection 必须完整符合 RunCasesRequest；信息不足时返回 clarify，"
                        "只问一个关键问题。用户会话绑定 Target 时不得扩大到其他 Target。"
                        "回答使用用户当前语言，中文请求必须中文回答。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current_time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                            "workspace_target_id": session.workspace_id,
                            "request": user_content,
                            "context": context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            json_schema=BasicAssistantOutput.model_json_schema(),
            base_url=self._config.base_url,
            model=self._config.model,
            api_key=api_key,
            timeout_seconds=self._config.timeout_seconds,
            options=self._config.options,
        )
        answer = BasicAssistantOutput.model_validate(output.value)
        plan_id: str | None = None
        if answer.kind == "create_plan":
            if answer.selection is None:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "模型请求创建计划但没有给出 selection",
                )
            self._require_workspace_target(session.workspace_id, answer.selection)
            plan = await self._plans.create(
                EvaluationPlanCreate(
                    session_id=session_id,
                    source_turn_id=turn_id,
                    goal=answer.goal or {"objective": user_content},
                    selection=answer.selection,
                    reasoning_summary={
                        "summary": answer.content,
                        "provider": "openai_compatible",
                    },
                    created_by=_ACTOR_ID,
                )
            )
            plan_id = plan.id
        await self._assistant.append_event(
            session_id,
            AssistantEventType.ASSISTANT_MESSAGE,
            actor_type=ActorType.MANAGER,
            actor_id=_ACTOR_ID,
            payload={
                "content": answer.content,
                "source": "basic_model_provider",
                "response_kind": answer.kind,
            },
            turn_id=turn_id,
            plan_id=plan_id,
            delivery_status=DeliveryStatus.LOCAL,
        )
        return {**output.metadata, "provider": "openai_compatible"}

    async def _handle_plan_action(
        self,
        event: AssistantEventView,
        action: dict[str, object],
    ) -> dict[str, object]:
        session_id = event.session_id
        turn_id = str(event.turn_id)
        event_id = event.id
        actor_id = event.actor_id
        plan_id = str(action.get("plan_id") or "")
        action_type = str(action.get("action_type") or "")
        plan = await self._plans.get(plan_id)
        if plan.session_id != session_id:
            raise AgentRigError(ErrorCode.PERMISSION_DENIED, "计划不属于当前评测会话")
        run_id: str | None = None
        if action_type == "confirm_plan":
            plan = await self._plans.confirm(
                plan_id,
                EvaluationPlanConfirm(
                    confirmation_event_id=event_id,
                    confirmed_by=actor_id,
                ),
            )
            content = f"计划 `{plan.id}` revision {plan.revision} 已确认，尚未创建 Run。"
        elif action_type == "submit_plan":
            plan, run = await self._plans.submit(
                plan_id,
                EvaluationPlanSubmit(idempotency_key=f"basic:{event_id}"),
            )
            run_id = run.run_id
            content = f"计划 `{plan.id}` 已提交，Run `{run.run_id}` 正在异步执行。"
        elif action_type == "cancel_plan":
            plan = await self._plans.cancel(
                plan_id,
                confirmation_event_id=event_id,
            )
            content = f"计划 `{plan.id}` 已取消，没有创建新的 Run。"
        else:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                f"基础智能助手不支持计划动作: {action_type}",
            )
        await self._assistant.append_event(
            session_id,
            AssistantEventType.ASSISTANT_MESSAGE,
            actor_type=ActorType.MANAGER,
            actor_id=_ACTOR_ID,
            payload={"content": content, "source": "basic_model_provider"},
            turn_id=turn_id,
            plan_id=plan_id,
            run_id=run_id,
            delivery_status=DeliveryStatus.LOCAL,
        )
        return {"provider": "agentrig_core", "action_type": action_type}

    async def _compact_context(self, session_id: str) -> dict[str, object]:
        session_context = await self._assistant.get_context(session_id)
        cases = await self._cases.list_cases(CaseSelector(), limit=100, offset=0)
        targets = await self._targets.list_targets(limit=100, offset=0)
        profiles = await self._profiles.list_profiles(limit=100, offset=0)
        runs = await self._runs.list_runs(limit=20, offset=0)
        return {
            "active_plan": session_context.get("active_plan"),
            "recent_messages": [
                {
                    "event_type": item.get("event_type"),
                    "actor_type": item.get("actor_type"),
                    "content": (item.get("payload") or {}).get("content"),
                }
                for item in session_context.get("recent_events", [])
                if isinstance(item, dict) and isinstance(item.get("payload"), dict)
            ][-8:],
            "targets": [
                {"id": item.id, "name": item.name, "driver_type": item.driver_type}
                for item in targets.items
            ],
            "cases": [
                {
                    "id": item.id,
                    "name": item.name,
                    "review_status": item.review_status.value,
                    "tags": item.tags,
                }
                for item in cases.items
            ],
            "profiles": [
                {"id": item.id, "name": item.name}
                for item in profiles.items
            ],
            "recent_runs": [
                {
                    "id": item.id,
                    "status": item.status.value,
                    "cell_count": item.cell_count,
                    "attempt_count": item.attempt_count,
                    "failed_count": item.failed_count,
                }
                for item in runs.items
            ],
        }

    @staticmethod
    def _require_workspace_target(workspace_id: str, selection: object) -> None:
        if workspace_id == "default":
            return
        targets = getattr(selection, "targets")
        if any(item.target_id != workspace_id for item in targets):
            raise AgentRigError(
                ErrorCode.PERMISSION_DENIED,
                "基础智能助手不能把当前会话扩大到其他 Target",
                details={"workspace_target_id": workspace_id},
            )


def _public_error(exc: Exception) -> str:
    if isinstance(exc, AgentRigError):
        return exc.detail.message
    return "智能助手处理失败，请检查模型 Provider 配置后重试。"
