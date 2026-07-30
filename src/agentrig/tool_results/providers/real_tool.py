"""Real Tool Provider 与 MCP backend 适配。"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from mcp import types

from ...proxy.backend import NAMESPACE_SEP, BackendRegistry
from .base import ProviderContext, ProviderResponse, ProviderStatus


class RealToolClient(Protocol):
    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any: ...


class McpBackendRealToolClient:
    def __init__(self, registry: BackendRegistry) -> None:
        self._registry = registry

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if NAMESPACE_SEP not in tool_name:
            raise ValueError("real MCP tool name must include namespace__tool")
        namespace, real_name = tool_name.split(NAMESPACE_SEP, 1)
        session = self._registry.get(namespace)
        if session is None:
            raise ValueError(f"real tool backend is not connected: {namespace}")
        response = await session.call_tool(real_name, arguments)
        if response.isError:
            raise RuntimeError(self._content(response.content))
        structured = getattr(response, "structuredContent", None)
        return structured if structured is not None else self._content(response.content)

    @staticmethod
    def _content(blocks: list[types.ContentBlock]) -> Any:
        text = [
            block.text
            for block in blocks
            if isinstance(block, types.TextContent)
        ]
        if len(text) == 1:
            return text[0]
        return text


class RealToolProvider:
    name = "real_tool"

    def __init__(
        self,
        client: RealToolClient,
        *,
        allowlist: list[str],
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._allowlist = set(allowlist)
        self._timeout_seconds = timeout_seconds

    async def resolve(self, context: ProviderContext) -> ProviderResponse:
        if not self._allowed(context.tool_call.name):
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                message="real tool is not in the deployment allowlist",
                metadata={"tool_name": context.tool_call.name},
            )
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._client.call(
                    context.tool_call.name,
                    context.tool_call.arguments,
                )
        except TimeoutError:
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                message=f"real tool exceeded {self._timeout_seconds} seconds",
            )
        except Exception as exc:
            return ProviderResponse(
                status=ProviderStatus.ERROR,
                message=f"real tool failed: {exc}",
            )
        return ProviderResponse(
            status=ProviderStatus.HIT,
            result=result,
            metadata={"tool_name": context.tool_call.name},
        )

    def _allowed(self, tool_name: str) -> bool:
        if tool_name in self._allowlist:
            return True
        if NAMESPACE_SEP in tool_name:
            namespace = tool_name.split(NAMESPACE_SEP, 1)[0]
            return f"{namespace}:*" in self._allowlist
        return False
