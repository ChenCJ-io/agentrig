"""Sample 审核边界和 CRUD 规则。"""

from __future__ import annotations

from typing import Protocol

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from .models import SampleStatus
from .repository import SampleRepository
from .schemas import SampleCreate, SamplePage, SamplePatch, SampleView


class ToolCallEvidenceReader(Protocol):
    """从持久化事件创建 Sample 草稿时需要的最小读取协议。"""

    async def sample_source(self, tool_call_id: str) -> dict[str, object] | None:
        ...


class SampleService:
    def __init__(
        self,
        repository: SampleRepository,
        *,
        evidence_reader: ToolCallEvidenceReader | None = None,
    ) -> None:
        self._repository = repository
        self._evidence_reader = evidence_reader

    async def create(self, value: SampleCreate) -> SampleView:
        resolved = value
        source_type = "manual"
        if value.source_tool_call_id:
            if self._evidence_reader is None:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "creating a sample from a tool call is not available",
                )
            source = await self._evidence_reader.sample_source(value.source_tool_call_id)
            if source is None:
                raise AgentRigError(
                    ErrorCode.NOT_FOUND,
                    f"tool call evidence not found: {value.source_tool_call_id}",
                )
            resolved = SampleCreate.model_validate(
                {
                    **value.model_dump(),
                    "tool_name": source["tool_name"],
                    "match_arguments": source["arguments"],
                    "content": source["result"],
                }
            )
            source_type = "real_tool"
        sample_id = resolved.id or new_id("sample")
        if await self._repository.get(sample_id) is not None:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"sample already exists: {sample_id}",
                details={"sample_id": sample_id},
            )
        return await self._repository.create(
            sample_id,
            resolved,
            source_type=source_type,
        )

    async def get(self, sample_id: str) -> SampleView:
        sample = await self._repository.get(sample_id)
        if sample is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"sample not found: {sample_id}",
                details={"sample_id": sample_id},
            )
        return sample

    async def list_samples(
        self,
        *,
        status: SampleStatus | None = None,
        tool_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SamplePage:
        return await self._repository.list_page(
            status=status,
            tool_name=tool_name,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def update(self, sample_id: str, patch: SamplePatch) -> SampleView:
        current = await self.get(sample_id)
        self._ensure_draft(current)
        data = current.model_dump(
            exclude={"id", "status", "source_type", "created_at", "updated_at"}
        )
        merged = {**data, **patch.model_dump(exclude_unset=True), "id": sample_id}
        value = SampleCreate.model_validate(merged)
        return await self._repository.update(sample_id, value)

    async def delete(self, sample_id: str) -> None:
        current = await self.get(sample_id)
        self._ensure_draft(current)
        await self._repository.delete(sample_id)

    async def review(self, sample_id: str, status: SampleStatus) -> SampleView:
        if status not in {SampleStatus.APPROVED, SampleStatus.DISABLED}:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "human review can only approve or disable a sample",
            )
        await self.get(sample_id)
        return await self._repository.set_status(sample_id, status)

    @staticmethod
    def _ensure_draft(value: SampleView) -> None:
        if value.status is not SampleStatus.DRAFT:
            raise AgentRigError(
                ErrorCode.PERMISSION_DENIED,
                "only draft samples can be modified or deleted",
                details={"sample_id": value.id, "status": value.status},
            )
