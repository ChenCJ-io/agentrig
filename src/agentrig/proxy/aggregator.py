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
        backend_tools: list[types.Tool] = []
        for ns, sess in self.backends.all().items():
            result = await sess.list_tools()
            for t in result.tools:
                backend_tools.append(
                    types.Tool(
                        name=f"{ns}{NAMESPACE_SEP}{t.name}",
                        description=t.description,
                        inputSchema=t.inputSchema,
                        outputSchema=t.outputSchema,
                    )
                )
        self._tool_definitions = {tool.name: tool for tool in backend_tools}
        tools = list(backend_tools)
        known_names = {tool.name for tool in tools}
        scope = self._scope()
        if scope is not None:
            declared_reader = getattr(scope, "declared_tools", None)
            for item in declared_reader() if declared_reader is not None else []:
                tool = _declared_tool(item)
                if tool.name in known_names:
                    continue
                tools.append(tool)
                known_names.add(tool.name)
            for fixture in scope.all_fixtures():
                name = str(fixture["tool_name"])
                if name in known_names:
                    continue
                arguments = fixture.get("match_arguments")
                result = fixture.get("result")
                tools.append(
                    types.Tool(
                        name=name,
                        description=(
                            f"Tool {name}. AgentRig supplies its result for this test case."
                        ),
                        inputSchema=_input_schema(arguments),
                        outputSchema=_schema_for_value(result),
                    )
                )
                known_names.add(name)
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        """使用请求携带的短期 Scope 调用该 CaseRun 的 Provider 链。"""
        scope = self._scope()
        if scope is None:
            scope_token = self._scope_token()
            if scope_token:
                return _error_result("proxy scope is invalid or expired")
            return _error_result("X-AgentRig-Proxy-Scope header is required")
        definition = self._tool_definitions.get(name)
        fixture_reader = getattr(scope, "current_fixture", None)
        fixture = fixture_reader(name) if fixture_reader is not None else None
        declared_reader = getattr(scope, "declared_tools", None)
        declared = (
            next(
                (
                    item
                    for item in declared_reader()
                    if item.get("name") == name
                ),
                None,
            )
            if declared_reader is not None
            else None
        )
        result_schema = (
            _schema_for_value(fixture.get("result"))
            if fixture is not None
            else dict(declared["outputSchema"])
            if declared is not None
            and isinstance(declared.get("outputSchema"), dict)
            else definition.outputSchema if definition is not None else None
        )
        try:
            result = await scope.resolve(
                name,
                arguments,
                result_schema=result_schema,
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

    def _scope(self) -> Any | None:
        token = self._scope_token()
        if not token or self.scope_registry is None:
            return None
        return self.scope_registry.get(token)

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


def _input_schema(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {"type": "object", "additionalProperties": True}
    return {
        "type": "object",
        "properties": {
            str(name): _schema_for_value(value)
            for name, value in arguments.items()
        },
        "required": [str(name) for name in arguments],
        "additionalProperties": True,
    }


def _declared_tool(value: dict[str, Any]) -> types.Tool:
    name = value.get("name")
    input_schema = value.get("inputSchema")
    output_schema = value.get("outputSchema")
    if not isinstance(name, str) or not name:
        raise RuntimeError("target tool_catalog item requires a non-empty name")
    if not isinstance(input_schema, dict):
        raise RuntimeError(f"target tool_catalog {name} requires inputSchema")
    if output_schema is not None and not isinstance(output_schema, dict):
        raise RuntimeError(f"target tool_catalog {name} outputSchema must be an object")
    return types.Tool(
        name=name,
        description=str(value.get("description") or f"Tool {name}"),
        inputSchema=input_schema,
        outputSchema=output_schema,
    )


def _schema_for_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _schema_for_value(value[0]) if value else {},
        }
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {
                str(name): _schema_for_value(nested)
                for name, nested in value.items()
            },
            "required": [str(name) for name in value],
            "additionalProperties": True,
        }
    return {}
