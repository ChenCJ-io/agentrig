"""AgentRig V1 CaseRun 级 MCP Proxy。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mcp import types
from mcp.server.lowlevel.server import Server

from .backend import NAMESPACE_SEP, BackendRegistry

if TYPE_CHECKING:
    from .scoped import ProxyScopeRegistry


class AgentRigProxy:
    """MCP proxy/aggregator 核心。"""

    def __init__(
        self,
        backends: BackendRegistry,
        *,
        scope_registry: ProxyScopeRegistry | None = None,
    ) -> None:
        self.backends = backends
        self.scope_registry = scope_registry
        self._server: Server | None = None
        self._tool_definitions: dict[str, types.Tool] = {}

    async def list_tools(self) -> list[types.Tool]:
        """聚合所有后端工具，加命名空间前缀（如 fs__read_file）。"""
        tools: list[types.Tool] = []
        for ns, sess in self.backends.all().items():
            result = await sess.list_tools()
            for t in result.tools:
                tools.append(
                    types.Tool(
                        name=f"{ns}{NAMESPACE_SEP}{t.name}",
                        description=t.description,
                        inputSchema=t.inputSchema,
                        outputSchema=t.outputSchema,
                    )
                )
        self._tool_definitions = {tool.name: tool for tool in tools}
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """使用请求携带的短期 Scope 调用该 CaseRun 的 Provider 链。"""
        scope_token = self._scope_token()
        if not scope_token:
            return _error_result("X-AgentRig-Proxy-Scope header is required")
        if self.scope_registry is None:
            return _error_result("scoped proxy is unavailable")
        scope = self.scope_registry.get(scope_token)
        if scope is None:
            return _error_result("proxy scope is invalid or expired")
        definition = self._tool_definitions.get(name)
        try:
            result = await scope.resolve(
                name,
                arguments,
                result_schema=definition.outputSchema if definition is not None else None,
            )
        except Exception as exc:
            return _error_result(str(exc))
        return _value_result(result.result)

    def _scope_token(self) -> str | None:
        if self._server is None:
            return None
        try:
            request = self._server.request_context.request
        except LookupError:
            return None
        if request is None:
            return None
        token = request.headers.get("x-agentrig-proxy-scope")
        if token:
            return str(token)
        query_token = request.query_params.get("agentrig_scope")
        return str(query_token) if query_token else None

    def build_server(self) -> Server:
        """构建 low-level MCP Server（注册 list_tools / call_tool handler）。

        返回的 Server 用 StreamableHTTPSessionManager + StreamableHTTPASGIApp
        挂到 FastAPI（见 server.py）。
        """
        if self._server is None:
            server = Server("agentrig-proxy")

            # MCP low-level Server 装饰器本身缺类型注解（SDK 限制），
            # 这里局部抑制；handler 体委托给有类型的方法，本身类型安全。
            @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
            async def _list() -> list[types.Tool]:
                return await self.list_tools()

            @server.call_tool()  # type: ignore[untyped-decorator]
            async def _call(
                name: str, arguments: dict[str, Any]
            ) -> types.CallToolResult:
                return await self.call_tool(name, arguments)

            self._server = server
        return self._server

def _value_result(value: Any) -> types.CallToolResult:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structuredContent=value if isinstance(value, dict) else None,
        isError=False,
    )


def _error_result(msg: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"[proxy error] {msg}")],
        isError=True,
    )
