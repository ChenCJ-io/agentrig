"""后端 MCP server 连接管理（命名空间 -> session）。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

NAMESPACE_SEP = "__"


class BackendRegistry:
    """后端 MCP server 注册表，按命名空间索引。

    session 是 duck-typed：测试注入 stub，正式运行注入 mcp.ClientSession。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}

    def add(self, namespace: str, session: Any) -> None:
        """注册一个后端，namespace 不能含命名空间分隔符。"""
        if NAMESPACE_SEP in namespace:
            raise ValueError(f"namespace 不能包含 {NAMESPACE_SEP!r}: {namespace}")
        self._sessions[namespace] = session

    def get(self, namespace: str) -> Any | None:
        """按命名空间取后端 session。"""
        return self._sessions.get(namespace)

    def all(self) -> dict[str, Any]:
        """返回 namespace -> session 的快照。"""
        return dict(self._sessions)


@asynccontextmanager
async def connect_backend(url: str) -> AsyncIterator[ClientSession]:
    """连一个后端 MCP server（streamable HTTP），返回初始化好的 ClientSession。

    长连复用 —— 在 proxy 整个生命周期内持有，不要每次调用重建。
    退出 context 时自动发 DELETE 终止会话。
    """
    async with streamable_http_client(url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
