"""ExecutionProfile 存储接口。"""

from __future__ import annotations

from typing import Protocol

from .schemas import ProfileCreate, ProfilePage, ProfileView


class ProfileRepository(Protocol):
    async def create(self, profile_id: str, value: ProfileCreate) -> ProfileView: ...

    async def get(self, profile_id: str) -> ProfileView | None: ...

    async def list_page(self, *, limit: int, offset: int) -> ProfilePage: ...

    async def update(self, profile_id: str, value: ProfileCreate) -> ProfileView: ...

    async def delete(self, profile_id: str) -> bool: ...
