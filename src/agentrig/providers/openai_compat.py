"""OpenAI 兼容 LLM provider（httpx 调 `/chat/completions`）。

适配任何 OpenAI Chat Completions 兼容的 endpoint（OpenAI / DashScope 兼容模式 /
本地 vLLM / LM Studio 等）。transport 参数供测试注入 httpx.MockTransport。
"""
from __future__ import annotations

from typing import Any

import httpx


class OpenAICompatProvider:
    """调 OpenAI 兼容 endpoint（`{base_url}/chat/completions`）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        request_timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.request_timeout = request_timeout
        self._transport = transport

    async def generate(
        self, messages: list[dict[str, str]], *, model: str | None = None
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload: dict[str, Any] = {"model": model or self.model, "messages": messages}
        client_kwargs: dict[str, Any] = {"timeout": self.request_timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return str(data["choices"][0]["message"]["content"])
