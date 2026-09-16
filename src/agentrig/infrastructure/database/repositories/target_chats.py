"""Target 直连会话的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select, update

from ....target_chat import TargetChatPage, TargetChatView
from ..orm import TargetChatSessionORM, utc_now
from ..session import Database


class SqlTargetChatRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def save(self, value: TargetChatView) -> None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TargetChatSessionORM).where(
                    TargetChatSessionORM.id == value.id,
                    TargetChatSessionORM.project_id == self._project_id,
                )
            )
            events = [event.model_dump(mode="json") for event in value.events]
            if row is None:
                row = TargetChatSessionORM(
                    id=value.id,
                    project_id=self._project_id,
                    target_id=value.target_id,
                    profile_id=value.profile_id,
                    version=value.version,
                    status=value.status,
                    events=events,
                    created_at=value.created_at,
                    updated_at=value.updated_at,
                )
                session.add(row)
            else:
                row.status = value.status
                row.events = events
                row.updated_at = value.updated_at
            await session.commit()

    async def get(self, chat_id: str) -> TargetChatView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TargetChatSessionORM).where(
                    TargetChatSessionORM.id == chat_id,
                    TargetChatSessionORM.project_id == self._project_id,
                )
            )
            return self._view(row) if row is not None else None

    async def list_page(
        self,
        *,
        target_id: str | None,
        limit: int,
        offset: int,
    ) -> TargetChatPage:
        filters = [TargetChatSessionORM.project_id == self._project_id]
        if target_id:
            filters.append(TargetChatSessionORM.target_id == target_id)
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(TargetChatSessionORM.id)).where(*filters)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(TargetChatSessionORM)
                    .where(*filters)
                    .order_by(
                        TargetChatSessionORM.updated_at.desc(),
                        TargetChatSessionORM.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return TargetChatPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def mark_open_interrupted(self) -> int:
        async with self._database.session() as session:
            result = await session.execute(
                update(TargetChatSessionORM)
                .where(
                    TargetChatSessionORM.status == "open",
                    TargetChatSessionORM.project_id == self._project_id,
                )
                .values(status="interrupted", updated_at=utc_now())
            )
            await session.commit()
            return int(getattr(result, "rowcount", 0) or 0)

    @staticmethod
    def _view(row: TargetChatSessionORM) -> TargetChatView:
        return TargetChatView.model_validate(
            {
                "id": row.id,
                "target_id": row.target_id,
                "profile_id": row.profile_id,
                "version": row.version,
                "status": row.status,
                "events": row.events,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
