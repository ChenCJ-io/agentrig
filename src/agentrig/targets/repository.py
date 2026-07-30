"""Target SQL 存储的协议。"""

from __future__ import annotations

from typing import Protocol

from .schemas import TargetCreate, TargetPage, TargetView


class TargetRepository(Protocol):
    async def create(self, target_id: str, value: TargetCreate) -> TargetView: ...

    async def get(self, target_id: str) -> TargetView | None: ...

    async def list_page(self, *, limit: int, offset: int) -> TargetPage: ...

    async def update(self, target_id: str, value: TargetCreate) -> TargetView: ...

    async def delete(self, target_id: str) -> bool: ...
