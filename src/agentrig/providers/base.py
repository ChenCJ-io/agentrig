"""LLM provider 抽象：统一的 LLM 调用接口（OpenAI 兼容语义）。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """LLM provider 接口：给定 messages，返回生成文本。"""

    async def generate(
        self, messages: list[dict[str, str]], *, model: str | None = None
    ) -> str: ...
