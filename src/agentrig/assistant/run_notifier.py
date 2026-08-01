"""Run 终态到 Assistant/Manager 主动总结回合的幂等桥。"""

from __future__ import annotations

import logging

from ..integrations.agentteams.bridge import AgentTeamsBridge
from ..runs.schemas import RunView
from .models import AssistantEventType
from .repository import AssistantRepository
from .service import AssistantService

logger = logging.getLogger("agentrig.assistant.run_notifier")


class AssistantRunNotifier:
    def __init__(
        self,
        *,
        repository: AssistantRepository,
        assistant: AssistantService,
        bridge: AgentTeamsBridge,
    ) -> None:
        self._repository = repository
        self._assistant = assistant
        self._bridge = bridge

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
                "content": f"Run {run.id} finished as {run.status.value}; diagnose and summarize it.",
                "status": run.status.value,
                "completed_count": run.completed_count,
                "failed_count": run.failed_count,
                "skipped_count": run.skipped_count,
            },
            plan_id=plan.id,
            run_id=run.id,
        )
        if not self._bridge.enabled:
            return
        try:
            await self._bridge.dispatch_user_message(event.id, turn.id)
        except Exception:
            logger.exception("failed to dispatch run completion for %s", run.id)
