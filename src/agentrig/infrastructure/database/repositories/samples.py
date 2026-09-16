"""共享工具结果 Sample 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, or_, select

from ....tool_results.models import SampleStatus
from ....tool_results.schemas import SampleCreate, SamplePage, SampleView
from ..orm import SampleORM, utc_now
from ..session import Database


class SqlSampleRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create(
        self,
        sample_id: str,
        value: SampleCreate,
        *,
        source_type: str,
    ) -> SampleView:
        row = SampleORM(
            id=sample_id,
            project_id=self._project_id,
            name=value.name,
            tool_name=value.tool_name,
            sample_kind=value.sample_kind.value,
            content=value.content,
            match_arguments=value.match_arguments,
            ignored_argument_paths=value.ignored_argument_paths,
            supported_versions=value.supported_versions,
            status=SampleStatus.DRAFT.value,
            source_type=source_type,
            source_tool_call_id=value.source_tool_call_id,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        result = await self.get(sample_id)
        assert result is not None
        return result

    async def get(self, sample_id: str) -> SampleView | None:
        async with self._database.session() as session:
            row = await session.get(SampleORM, sample_id)
            return (
                self._view(row)
                if row is not None and row.project_id == self._project_id
                else None
            )

    async def list_page(
        self,
        *,
        status: SampleStatus | None,
        tool_name: str | None,
        limit: int,
        offset: int,
    ) -> SamplePage:
        query = select(SampleORM).where(SampleORM.project_id == self._project_id)
        count_query = select(func.count(SampleORM.id)).where(
            SampleORM.project_id == self._project_id
        )
        if status is not None:
            query = query.where(SampleORM.status == status.value)
            count_query = count_query.where(SampleORM.status == status.value)
        if tool_name is not None:
            query = query.where(SampleORM.tool_name == tool_name)
            count_query = count_query.where(SampleORM.tool_name == tool_name)
        async with self._database.session() as session:
            total = int(await session.scalar(count_query) or 0)
            rows = list(
                await session.scalars(
                    query.order_by(SampleORM.created_at, SampleORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return SamplePage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def update(self, sample_id: str, value: SampleCreate) -> SampleView:
        async with self._database.session() as session:
            row = await session.get(SampleORM, sample_id)
            assert row is not None and row.project_id == self._project_id
            row.name = value.name
            row.tool_name = value.tool_name
            row.sample_kind = value.sample_kind.value
            row.content = value.content
            row.match_arguments = value.match_arguments
            row.ignored_argument_paths = value.ignored_argument_paths
            row.supported_versions = value.supported_versions
            row.updated_at = utc_now()
            await session.commit()
        result = await self.get(sample_id)
        assert result is not None
        return result

    async def delete(self, sample_id: str) -> bool:
        async with self._database.session() as session:
            row = await session.get(SampleORM, sample_id)
            if row is None or row.project_id != self._project_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def set_status(self, sample_id: str, status: SampleStatus) -> SampleView:
        async with self._database.session() as session:
            row = await session.get(SampleORM, sample_id)
            assert row is not None and row.project_id == self._project_id
            row.status = status.value
            row.updated_at = utc_now()
            await session.commit()
        result = await self.get(sample_id)
        assert result is not None
        return result

    async def approved_candidates(
        self,
        tool_name: str,
        version: str | None,
    ) -> list[SampleView]:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(SampleORM)
                    .where(
                        SampleORM.project_id == self._project_id,
                        or_(
                            SampleORM.tool_name == tool_name,
                            SampleORM.sample_kind == "sequence",
                        ),
                        SampleORM.status == SampleStatus.APPROVED.value,
                    )
                    .order_by(SampleORM.created_at, SampleORM.id)
                )
            )
        return [
            self._view(row)
            for row in rows
            if not row.supported_versions
            or "*" in row.supported_versions
            or version in row.supported_versions
        ]

    @staticmethod
    def _view(row: SampleORM) -> SampleView:
        return SampleView.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "tool_name": row.tool_name,
                "sample_kind": row.sample_kind,
                "content": row.content,
                "match_arguments": row.match_arguments,
                "ignored_argument_paths": row.ignored_argument_paths,
                "supported_versions": row.supported_versions,
                "status": row.status,
                "source_type": row.source_type,
                "source_tool_call_id": row.source_tool_call_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
