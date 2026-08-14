"""ExecutionProfile 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select

from ....profiles.schemas import ProfileCreate, ProfilePage, ProfileView
from ..orm import ExecutionProfileORM, utc_now
from ..session import Database


class SqlProfileRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create(self, profile_id: str, value: ProfileCreate) -> ProfileView:
        row = ExecutionProfileORM(
            id=profile_id,
            project_id=self._project_id,
            name=value.name,
            description=value.description,
            config=value.config.model_dump(mode="json"),
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        result = await self.get(profile_id)
        assert result is not None
        return result

    async def get(self, profile_id: str) -> ProfileView | None:
        async with self._database.session() as session:
            row = await session.get(ExecutionProfileORM, profile_id)
            return (
                self._view(row)
                if row is not None and row.project_id == self._project_id
                else None
            )

    async def list_page(self, *, limit: int, offset: int) -> ProfilePage:
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(ExecutionProfileORM.id)).where(
                        ExecutionProfileORM.project_id == self._project_id
                    )
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(ExecutionProfileORM)
                    .where(ExecutionProfileORM.project_id == self._project_id)
                    .order_by(ExecutionProfileORM.created_at, ExecutionProfileORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return ProfilePage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update(self, profile_id: str, value: ProfileCreate) -> ProfileView:
        async with self._database.session() as session:
            row = await session.get(ExecutionProfileORM, profile_id)
            assert row is not None and row.project_id == self._project_id
            row.name = value.name
            row.description = value.description
            row.config = value.config.model_dump(mode="json")
            row.updated_at = utc_now()
            await session.commit()
        result = await self.get(profile_id)
        assert result is not None
        return result

    async def delete(self, profile_id: str) -> bool:
        async with self._database.session() as session:
            row = await session.get(ExecutionProfileORM, profile_id)
            if row is None or row.project_id != self._project_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    @staticmethod
    def _view(row: ExecutionProfileORM) -> ProfileView:
        return ProfileView.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "config": row.config,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
