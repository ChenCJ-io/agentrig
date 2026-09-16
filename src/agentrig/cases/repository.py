"""测试用例存储接口，由 infrastructure 提供 SQLAlchemy 实现。"""

from __future__ import annotations

from typing import Protocol

from .models import ReviewStatus
from .schemas import CaseSelector, TagUsage, TestCaseCreate, TestCasePage, TestCaseView


class CaseRepository(Protocol):
    async def create(self, case_id: str, value: TestCaseCreate) -> TestCaseView: ...

    async def get(self, case_id: str) -> TestCaseView | None: ...

    async def list_page(
        self,
        selector: CaseSelector,
        *,
        limit: int,
        offset: int,
    ) -> TestCasePage: ...

    async def update(self, case_id: str, value: TestCaseCreate) -> TestCaseView: ...

    async def delete(self, case_id: str) -> bool: ...

    async def set_review_status(
        self,
        case_id: str,
        status: ReviewStatus,
    ) -> TestCaseView: ...

    async def list_tags(self) -> list[TagUsage]: ...
