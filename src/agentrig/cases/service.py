"""测试用例业务规则。"""

from __future__ import annotations

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from .models import ReviewStatus
from .repository import CaseRepository
from .schemas import (
    CaseSelector,
    TagUsage,
    TestCaseCreate,
    TestCasePage,
    TestCasePatch,
    TestCaseView,
)


class CaseService:
    def __init__(self, repository: CaseRepository) -> None:
        self._repository = repository

    async def create(self, value: TestCaseCreate) -> TestCaseView:
        case_id = value.id or new_id("case")
        if await self._repository.get(case_id) is not None:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"test case already exists: {case_id}",
                details={"case_id": case_id},
            )
        return await self._repository.create(case_id, value)

    async def get(self, case_id: str) -> TestCaseView:
        value = await self._repository.get(case_id)
        if value is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"test case not found: {case_id}",
                details={"case_id": case_id},
            )
        return value

    async def list_cases(
        self,
        selector: CaseSelector | None = None,
        *,
        limit: int = 50,
        offset: int = 0,
        apply_default_review_filter: bool = True,
    ) -> TestCasePage:
        resolved = selector or CaseSelector()
        if apply_default_review_filter and not resolved.review_status:
            resolved = resolved.model_copy(
                update={"review_status": [ReviewStatus.DRAFT, ReviewStatus.APPROVED]}
            )
        return await self._repository.list_page(
            resolved,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def update(self, case_id: str, patch: TestCasePatch) -> TestCaseView:
        current = await self.get(case_id)
        self._ensure_mutable(current)
        current_data = current.model_dump(
            exclude={"id", "review_status", "created_at", "updated_at"}
        )
        merged = {
            **current_data,
            **patch.model_dump(exclude_unset=True),
            "id": case_id,
        }
        validated = TestCaseCreate.model_validate(merged)
        return await self._repository.update(case_id, validated)

    async def delete(self, case_id: str) -> None:
        current = await self.get(case_id)
        self._ensure_mutable(current)
        await self._repository.delete(case_id)

    async def review(self, case_id: str, status: ReviewStatus) -> TestCaseView:
        if status is ReviewStatus.DRAFT:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "human review can only approve or reject a test case",
            )
        await self.get(case_id)
        return await self._repository.set_review_status(case_id, status)

    async def list_tags(self) -> list[TagUsage]:
        return await self._repository.list_tags()

    @staticmethod
    def _ensure_mutable(value: TestCaseView) -> None:
        if value.review_status is ReviewStatus.APPROVED:
            raise AgentRigError(
                ErrorCode.PERMISSION_DENIED,
                "approved test cases are immutable and cannot be deleted",
                details={"case_id": value.id},
            )
