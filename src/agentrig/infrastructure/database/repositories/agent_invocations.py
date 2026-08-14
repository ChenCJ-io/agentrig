"""AgentInvocation 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select

from ....agents.invocation_models import AgentInvocationStatus, AgentRole
from ....agents.invocation_schemas import (
    AgentInvocationCreate,
    AgentInvocationPage,
    AgentInvocationView,
)
from ..orm import AgentInvocationORM, utc_now
from ..session import Database


class SqlAgentInvocationRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create(
        self,
        invocation_id: str,
        value: AgentInvocationCreate,
        *,
        input_hash: str,
    ) -> AgentInvocationView:
        row = AgentInvocationORM(
            id=invocation_id,
            project_id=self._project_id,
            agent_role=value.role.value,
            status=AgentInvocationStatus.CREATED.value,
            session_id=value.context.session_id,
            plan_id=value.context.plan_id,
            run_id=value.context.run_id,
            case_run_id=value.context.case_run_id,
            tool_call_event_id=value.context.tool_call_event_id,
            attempt=value.attempt,
            input_snapshot=value.input_snapshot,
            input_hash=input_hash,
            matrix_room_id=value.matrix_room_id,
            deadline=value.deadline,
            idempotency_key=value.idempotency_key,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    async def get(self, invocation_id: str) -> AgentInvocationView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AgentInvocationORM).where(
                    AgentInvocationORM.id == invocation_id,
                    AgentInvocationORM.project_id == self._project_id,
                )
            )
        return self._view(row) if row is not None else None

    async def get_by_idempotency_key(
        self,
        role: AgentRole,
        idempotency_key: str,
    ) -> AgentInvocationView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AgentInvocationORM).where(
                    AgentInvocationORM.agent_role == role.value,
                    AgentInvocationORM.idempotency_key == idempotency_key,
                    AgentInvocationORM.project_id == self._project_id,
                )
            )
        return self._view(row) if row is not None else None

    async def list_for_session(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> AgentInvocationPage:
        where = (
            (AgentInvocationORM.session_id == session_id)
            & (AgentInvocationORM.project_id == self._project_id)
        )
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(AgentInvocationORM.id)).where(where)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(AgentInvocationORM)
                    .where(where)
                    .order_by(
                        AgentInvocationORM.created_at.desc(),
                        AgentInvocationORM.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return AgentInvocationPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_for_run(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> AgentInvocationPage:
        where = (
            (AgentInvocationORM.run_id == run_id)
            & (AgentInvocationORM.project_id == self._project_id)
        )
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(AgentInvocationORM.id)).where(where)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(AgentInvocationORM)
                    .where(where)
                    .order_by(
                        AgentInvocationORM.created_at.asc(),
                        AgentInvocationORM.id.asc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return AgentInvocationPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_all(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AgentInvocationPage:
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(AgentInvocationORM.id)).where(
                        AgentInvocationORM.project_id == self._project_id
                    )
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(AgentInvocationORM)
                    .where(AgentInvocationORM.project_id == self._project_id)
                    .order_by(
                        AgentInvocationORM.created_at.desc(),
                        AgentInvocationORM.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return AgentInvocationPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def set_status(
        self,
        invocation_id: str,
        status: AgentInvocationStatus,
        *,
        assigned_agent: str | None = None,
        matrix_room_id: str | None = None,
        request_event_id: str | None = None,
        response_event_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        result_hash: str | None = None,
        result_ref: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
    ) -> AgentInvocationView:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.scalar(
                select(AgentInvocationORM).where(
                    AgentInvocationORM.id == invocation_id,
                    AgentInvocationORM.project_id == self._project_id,
                )
            )
            assert row is not None
            row.status = status.value
            row.assigned_agent = assigned_agent or row.assigned_agent
            row.matrix_room_id = matrix_room_id or row.matrix_room_id
            row.request_event_id = request_event_id or row.request_event_id
            row.response_event_id = response_event_id or row.response_event_id
            row.result_payload = result_payload or row.result_payload
            row.result_hash = result_hash or row.result_hash
            row.result_ref = result_ref or row.result_ref
            row.error_code = error_code
            row.error_message = error_message
            row.retryable = retryable
            if status is AgentInvocationStatus.RUNNING and row.started_at is None:
                row.started_at = now
            if status.terminal:
                row.finished_at = now
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    async def cancel_non_terminal(self) -> None:
        now = utc_now()
        terminal = [
            AgentInvocationStatus.COMPLETED.value,
            AgentInvocationStatus.FAILED.value,
            AgentInvocationStatus.TIMED_OUT.value,
            AgentInvocationStatus.CANCELLED.value,
        ]
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(AgentInvocationORM).where(
                        AgentInvocationORM.status.not_in(terminal),
                        AgentInvocationORM.project_id == self._project_id,
                    )
                )
            )
            for row in rows:
                row.status = AgentInvocationStatus.CANCELLED.value
                row.error_code = "interrupted"
                row.error_message = "service restarted before the invocation completed"
                row.finished_at = now
            await session.commit()

    async def attach_result_ref(
        self,
        invocation_id: str,
        result_ref: str,
    ) -> AgentInvocationView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AgentInvocationORM).where(
                    AgentInvocationORM.id == invocation_id,
                    AgentInvocationORM.project_id == self._project_id,
                )
            )
            assert row is not None
            row.result_ref = result_ref
            # Worker 结果只在核心消费前暂存；事实落入 RunEvent/EvaluationResult 后即清除。
            row.result_payload = None
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    async def attach_response_event(
        self,
        invocation_id: str,
        response_event_id: str,
    ) -> AgentInvocationView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AgentInvocationORM).where(
                    AgentInvocationORM.id == invocation_id,
                    AgentInvocationORM.project_id == self._project_id,
                )
            )
            assert row is not None
            row.response_event_id = response_event_id
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    @staticmethod
    def _view(row: AgentInvocationORM) -> AgentInvocationView:
        return AgentInvocationView.model_validate(
            {
                "id": row.id,
                "agent_role": row.agent_role,
                "status": row.status,
                "session_id": row.session_id,
                "plan_id": row.plan_id,
                "run_id": row.run_id,
                "case_run_id": row.case_run_id,
                "tool_call_event_id": row.tool_call_event_id,
                "attempt": row.attempt,
                "input_snapshot": row.input_snapshot,
                "input_hash": row.input_hash,
                "result_payload": row.result_payload,
                "result_ref": row.result_ref,
                "result_hash": row.result_hash,
                "matrix_room_id": row.matrix_room_id,
                "request_event_id": row.request_event_id,
                "response_event_id": row.response_event_id,
                "assigned_agent": row.assigned_agent,
                "deadline": row.deadline,
                "idempotency_key": row.idempotency_key,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "retryable": bool(row.retryable),
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            }
        )
