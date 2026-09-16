"""测试用例的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ....cases.models import ReviewStatus
from ....cases.schemas import (
    CaseSelector,
    TagUsage,
    TestCaseCreate,
    TestCasePage,
    TestCaseView,
    TestTurn,
)
from ....identifiers import new_id
from ..orm import CaseTagORM, CaseTurnORM, TestCaseORM, utc_now
from ..session import Database


class SqlCaseRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create(self, case_id: str, value: TestCaseCreate) -> TestCaseView:
        row = self._new_row(case_id, value, project_id=self._project_id)
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        result = await self.get(case_id)
        assert result is not None
        return result

    async def get(self, case_id: str) -> TestCaseView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TestCaseORM)
                .where(
                    TestCaseORM.id == case_id,
                    TestCaseORM.project_id == self._project_id,
                )
                .options(
                    selectinload(TestCaseORM.turns),
                    selectinload(TestCaseORM.tags),
                )
            )
            return self._view(row) if row is not None else None

    async def list_page(
        self,
        selector: CaseSelector,
        *,
        limit: int,
        offset: int,
    ) -> TestCasePage:
        query = select(TestCaseORM).where(
            TestCaseORM.project_id == self._project_id
        ).options(
            selectinload(TestCaseORM.turns),
            selectinload(TestCaseORM.tags),
        )
        if selector.review_status:
            query = query.where(
                TestCaseORM.review_status.in_([status.value for status in selector.review_status])
            )
        query = query.order_by(TestCaseORM.created_at, TestCaseORM.id)
        async with self._database.session() as session:
            rows = list((await session.scalars(query)).unique())
        filtered = [row for row in rows if self._matches(row, selector)]
        items = [self._view(row) for row in filtered[offset : offset + limit]]
        return TestCasePage(items=items, total=len(filtered), limit=limit, offset=offset)

    async def update(self, case_id: str, value: TestCaseCreate) -> TestCaseView:
        async with self._database.session() as session:
            row = await session.scalar(
                select(TestCaseORM)
                .where(
                    TestCaseORM.id == case_id,
                    TestCaseORM.project_id == self._project_id,
                )
                .options(
                    selectinload(TestCaseORM.turns),
                    selectinload(TestCaseORM.tags),
                )
            )
            assert row is not None
            row.name = value.name
            row.description = value.description
            row.supported_versions = list(value.supported_versions)
            row.primary_evaluator = value.primary_evaluator
            row.initial_state = value.initial_state
            row.case_assertions = [
                item.model_dump(mode="json", exclude_none=True) for item in value.case_assertions
            ]
            row.case_rubric = value.case_rubric
            row.updated_at = utc_now()
            row.turns.clear()
            row.tags.clear()
            await session.flush()
            row.turns.extend(self._turn(row.id, turn) for turn in value.turns)
            row.tags.extend(CaseTagORM(case_id=row.id, tag=tag) for tag in value.tags)
            await session.commit()
        result = await self.get(case_id)
        assert result is not None
        return result

    async def delete(self, case_id: str) -> bool:
        async with self._database.session() as session:
            row = await session.get(TestCaseORM, case_id)
            if row is None or row.project_id != self._project_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def set_review_status(
        self,
        case_id: str,
        status: ReviewStatus,
    ) -> TestCaseView:
        async with self._database.session() as session:
            row = await session.get(TestCaseORM, case_id)
            assert row is not None and row.project_id == self._project_id
            row.review_status = status.value
            row.updated_at = utc_now()
            await session.commit()
        result = await self.get(case_id)
        assert result is not None
        return result

    async def list_tags(self) -> list[TagUsage]:
        async with self._database.session() as session:
            rows = (
                await session.execute(
                    select(CaseTagORM.tag, func.count(CaseTagORM.case_id))
                    .join(TestCaseORM, TestCaseORM.id == CaseTagORM.case_id)
                    .where(TestCaseORM.project_id == self._project_id)
                    .group_by(CaseTagORM.tag)
                    .order_by(CaseTagORM.tag)
                )
            ).all()
        return [TagUsage(tag=tag, count=count) for tag, count in rows]

    @staticmethod
    def _new_row(
        case_id: str,
        value: TestCaseCreate,
        *,
        project_id: str,
    ) -> TestCaseORM:
        row = TestCaseORM(
            id=case_id,
            project_id=project_id,
            name=value.name,
            description=value.description,
            review_status=ReviewStatus.DRAFT.value,
            supported_versions=list(value.supported_versions),
            primary_evaluator=value.primary_evaluator,
            initial_state=value.initial_state,
            case_assertions=[
                item.model_dump(mode="json", exclude_none=True) for item in value.case_assertions
            ],
            case_rubric=value.case_rubric,
        )
        row.turns = [SqlCaseRepository._turn(case_id, turn) for turn in value.turns]
        row.tags = [CaseTagORM(case_id=case_id, tag=tag) for tag in value.tags]
        return row

    @staticmethod
    def _turn(case_id: str, value: TestTurn) -> CaseTurnORM:
        return CaseTurnORM(
            id=new_id("turn"),
            case_id=case_id,
            position=value.position,
            user_message=value.user_message,
            simulation_instruction=value.simulation_instruction,
            fixtures=[item.model_dump(mode="json") for item in value.fixtures],
            assertions=[
                item.model_dump(mode="json", exclude_none=True) for item in value.assertions
            ],
            rubric=value.rubric,
        )

    @staticmethod
    def _view(row: TestCaseORM) -> TestCaseView:
        return TestCaseView.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "review_status": row.review_status,
                "tags": [item.tag for item in row.tags],
                "supported_versions": row.supported_versions,
                "primary_evaluator": row.primary_evaluator,
                "initial_state": row.initial_state,
                "case_assertions": row.case_assertions,
                "case_rubric": row.case_rubric,
                "turns": [
                    {
                        "position": item.position,
                        "user_message": item.user_message,
                        "simulation_instruction": item.simulation_instruction,
                        "fixtures": item.fixtures,
                        "assertions": item.assertions,
                        "rubric": item.rubric,
                    }
                    for item in row.turns
                ],
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @staticmethod
    def _matches(row: TestCaseORM, selector: CaseSelector) -> bool:
        tags = {item.tag for item in row.tags}
        if selector.tags and not tags.intersection(selector.tags):
            return False
        if selector.capabilities:
            capabilities = {
                value if value.startswith("cap.") else f"cap.{value}"
                for value in selector.capabilities
            }
            if not tags.intersection(capabilities):
                return False
        if selector.tool_names:
            known_tools = {tag.removeprefix("cap.") for tag in tags if tag.startswith("cap.")}
            for turn in row.turns:
                known_tools.update(item.get("tool_name", "") for item in turn.fixtures)
                known_tools.update(
                    item.get("tool_name", "")
                    for item in turn.assertions
                    if item.get("tool_name")
                )
            known_tools.update(
                item.get("tool_name", "")
                for item in row.case_assertions
                if item.get("tool_name")
            )
            if not known_tools.intersection(selector.tool_names):
                return False
        return True
