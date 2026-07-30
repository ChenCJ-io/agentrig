"""Sample 存储接口。"""

from __future__ import annotations

from typing import Protocol

from .models import SampleStatus
from .schemas import SampleCreate, SamplePage, SampleView


class SampleRepository(Protocol):
    async def create(
        self,
        sample_id: str,
        value: SampleCreate,
        *,
        source_type: str,
    ) -> SampleView: ...

    async def get(self, sample_id: str) -> SampleView | None: ...

    async def list_page(
        self,
        *,
        status: SampleStatus | None,
        tool_name: str | None,
        limit: int,
        offset: int,
    ) -> SamplePage: ...

    async def update(self, sample_id: str, value: SampleCreate) -> SampleView: ...

    async def delete(self, sample_id: str) -> bool: ...

    async def set_status(self, sample_id: str, status: SampleStatus) -> SampleView: ...

    async def approved_candidates(
        self,
        tool_name: str,
        version: str | None,
    ) -> list[SampleView]: ...
