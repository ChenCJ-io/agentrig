"""LLM provider 工厂：按配置返回 OpenAI 兼容 provider（未配全则返回 None）。"""

from __future__ import annotations

from ..config import get_settings
from .base import LLMProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["LLMProvider", "OpenAICompatProvider", "get_llm_provider"]


def get_llm_provider() -> LLMProvider | None:
    """按 settings.llm 返回 provider；api_key/base_url/model 任一缺失返回 None。"""
    cfg = get_settings().llm
    api_key = cfg.api_key.get_secret_value()
    if not api_key or not cfg.base_url or not cfg.model:
        return None
    return OpenAICompatProvider(
        base_url=cfg.base_url,
        api_key=api_key,
        model=cfg.model,
    )
