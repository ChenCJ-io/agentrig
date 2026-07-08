"""后端 MCP server 连接管理（命名空间 -> session）。

第一周只持有 session 引用（duck-typed：需 async list_tools() / async
call_tool(name, args)）。真实连接（streamable_http_client + ClientSession）
放 PR3b 在 lifespan 装配。
"""
from __future__ import annotations

from typing import Any

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
