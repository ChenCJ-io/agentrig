"""Target 直连会话持久化端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .target_chat import TargetChatPage, TargetChatView


class TargetChatRepository(Protocol):
    async def save(self, value: TargetChatView) -> None: ...

    async def get(self, chat_id: str) -> TargetChatView | None: ...

    async def list_page(
        self,
        *,
        target_id: str | None,
        limit: int,
        offset: int,
    ) -> TargetChatPage: ...

    async def mark_open_interrupted(self) -> int: ...
