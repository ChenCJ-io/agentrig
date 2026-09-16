"""ExecutionProfile CRUD 服务。"""

from __future__ import annotations

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from .repository import ProfileRepository
from .schemas import ProfileCreate, ProfilePage, ProfilePatch, ProfileView


class ProfileService:
    def __init__(self, repository: ProfileRepository) -> None:
        self._repository = repository

    async def create(self, value: ProfileCreate) -> ProfileView:
        profile_id = value.id or new_id("profile")
        if await self._repository.get(profile_id) is not None:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"execution profile already exists: {profile_id}",
                details={"profile_id": profile_id},
            )
        return await self._repository.create(profile_id, value)

    async def get(self, profile_id: str) -> ProfileView:
        profile = await self._repository.get(profile_id)
        if profile is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"execution profile not found: {profile_id}",
                details={"profile_id": profile_id},
            )
        return profile

    async def list_profiles(self, *, limit: int = 50, offset: int = 0) -> ProfilePage:
        return await self._repository.list_page(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def update(self, profile_id: str, patch: ProfilePatch) -> ProfileView:
        current = await self.get(profile_id)
        data = current.model_dump(exclude={"id", "created_at", "updated_at"})
        merged = {**data, **patch.model_dump(exclude_unset=True), "id": profile_id}
        value = ProfileCreate.model_validate(merged)
        return await self._repository.update(profile_id, value)

    async def delete(self, profile_id: str) -> None:
        await self.get(profile_id)
        await self._repository.delete(profile_id)
