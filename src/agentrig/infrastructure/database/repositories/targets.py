"""Target 与 TargetVersion 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ....identifiers import new_id
from ....targets.schemas import TargetCreate, TargetPage, TargetVersion, TargetView
from ..orm import TargetORM, TargetVersionORM, utc_now
from ..session import Database


class SqlTargetRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(self, target_id: str, value: TargetCreate) -> TargetView:
        row = self._new_row(target_id, value)
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        result = await self.get(target_id)
        assert result is not None
        return result

    async def get(self, target_id: str) -> TargetView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TargetORM)
                .where(TargetORM.id == target_id)
                .options(selectinload(TargetORM.versions))
            )
            return self._view(row) if row is not None else None

    async def list_page(self, *, limit: int, offset: int) -> TargetPage:
        async with self._database.session() as session:
            total = int(await session.scalar(select(func.count(TargetORM.id))) or 0)
            rows = list(
                (
                    await session.scalars(
                        select(TargetORM)
                        .options(selectinload(TargetORM.versions))
                        .order_by(TargetORM.created_at, TargetORM.id)
                        .limit(limit)
                        .offset(offset)
                    )
                ).unique()
            )
        return TargetPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update(self, target_id: str, value: TargetCreate) -> TargetView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TargetORM)
                .where(TargetORM.id == target_id)
                .options(selectinload(TargetORM.versions))
            )
            assert row is not None
            row.name = value.name
            row.driver_type = value.driver_type
            row.endpoint = value.endpoint
            row.secret_ref = value.secret_ref
            row.options = value.options
            row.updated_at = utc_now()
            row.versions.clear()
            await session.flush()
            row.versions.extend(self._version(target_id, item) for item in value.versions)
            await session.commit()
        result = await self.get(target_id)
        assert result is not None
        return result

    async def delete(self, target_id: str) -> bool:
        async with self._database.session() as session:
            row = await session.get(TargetORM, target_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    @staticmethod
    def _new_row(target_id: str, value: TargetCreate) -> TargetORM:
        row = TargetORM(
            id=target_id,
            name=value.name,
            driver_type=value.driver_type,
            endpoint=value.endpoint,
            secret_ref=value.secret_ref,
            options=value.options,
        )
        row.versions = [SqlTargetRepository._version(target_id, item) for item in value.versions]
        return row

    @staticmethod
    def _version(target_id: str, value: TargetVersion) -> TargetVersionORM:
        return TargetVersionORM(
            id=new_id("target_version"),
            target_id=target_id,
            version=value.version,
            endpoint_override=value.endpoint,
            options_override=value.options,
        )

    @staticmethod
    def _view(row: TargetORM) -> TargetView:
        return TargetView.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "driver_type": row.driver_type,
                "endpoint": row.endpoint,
                "secret_ref": row.secret_ref,
                "options": row.options,
                "versions": [
                    {
                        "version": item.version,
                        "endpoint": item.endpoint_override,
                        "options": item.options_override,
                    }
                    for item in row.versions
                ],
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
