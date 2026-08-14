"""Run 终态到 Assistant/Manager 主动总结回合的幂等桥。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..integrations.agentteams.bridge import AgentTeamsBridge
from ..runs.schemas import RunView
from .models import AssistantEventType
from .repository import AssistantRepository
from .service import AssistantService

if TYPE_CHECKING:
    from .basic_runtime import BasicAssistantRuntime

logger = logging.getLogger("agentrig.assistant.run_notifier")


class AssistantRunNotifier:
    def __init__(
        self,
        *,
        repository: AssistantRepository,
        assistant: AssistantService,
        bridge: AgentTeamsBridge,
        basic_runtime: BasicAssistantRuntime | None = None,
    ) -> None:
        self._repository = repository
        self._assistant = assistant
        self._bridge = bridge
        self._basic_runtime = basic_runtime

    async def __call__(self, run: RunView) -> None:
        plan = await self._repository.get_plan_by_run_id(run.id)
        if plan is None:
            return
        existing = await self._repository.get_linked_event(
            plan.session_id,
            event_type=AssistantEventType.RUN_STATUS.value,
            run_id=run.id,
        )
        if existing is not None:
            return
        event, turn = await self._assistant.create_system_turn(
            plan.session_id,
            event_type=AssistantEventType.RUN_STATUS,
            payload={
                "content": (
                    f"Run {run.id} 已进入终态 {run.status.value}。"
                    "请根据真实 Cell、Attempt 和评判证据总结结果，不要把运行完成等同于全部通过。"
                ),
                "status": run.status.value,
                "completed_count": run.completed_count,
                "failed_count": run.failed_count,
                "skipped_count": run.skipped_count,
            },
            plan_id=plan.id,
            run_id=run.id,
        )
        if self._bridge.enabled:
            try:
                health = await self._bridge.health()
                if (
                    health.configured
                    and health.matrix_reachable
                    and health.runtime_reachable is not False
                ):
                    await self._bridge.dispatch_user_message(event.id, turn.id)
                    return
            except Exception:
                logger.exception("failed to dispatch run completion for %s", run.id)
        if self._basic_runtime is not None and self._basic_runtime.health().available:
            await self._basic_runtime.process(event.id, turn.id)
