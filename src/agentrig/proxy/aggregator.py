"""AgentRig MCP Proxy/Aggregator 核心逻辑。

聚合多个后端 MCP server 的工具（加命名空间前缀）暴露给 agent；call_tool 时
按命名空间路由，转发前检查 mock，转发后记 trace（含返回结果，供采样）。

对上是 low-level MCP server（build_server()），对下用 BackendRegistry 持有
后端 session。mock 生成与 trace 在这里 —— 不在后端 session，便于单测和换策略。
"""
from __future__ import annotations

from typing import Any

from mcp import types
from mcp.server.lowlevel.server import Server

from .backend import NAMESPACE_SEP, BackendRegistry
from .mock_policy import MockPolicy
from .trace import TraceEntry, TraceSink


class AgentRigProxy:
    """MCP proxy/aggregator 核心。"""

    def __init__(
        self,
        backends: BackendRegistry,
        *,
        mock_policy: MockPolicy | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self.backends = backends
        self.mock_policy = mock_policy
        self.trace_sink = trace_sink
        self._server: Server | None = None

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
                    )
                )
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> list[types.ContentBlock]:
        """路由一次工具调用：mock 命中则返回预设；否则转发后端 + 记 trace。"""
        # 1. mock 命中？命中即返回，不转发
        if self.mock_policy is not None and self.mock_policy.should_mock(name, arguments):
            value = self.mock_policy.generate(name, arguments)
            content = _to_content(value)
            if self.trace_sink is not None:
                self.trace_sink.record(
                    TraceEntry(name, arguments, source="mock", result=value)
                )
            return content

        # 2. 路由转发到后端
        if NAMESPACE_SEP not in name:
            return _error_content(f"unknown tool (no namespace): {name}")
        ns, real = name.split(NAMESPACE_SEP, 1)
        sess = self.backends.get(ns)
        if sess is None:
            return _error_content(f"unknown backend: {ns}")
        try:
            result = await sess.call_tool(real, arguments)
        except Exception as e:
            if self.trace_sink is not None:
                self.trace_sink.record(
                    TraceEntry(
                        name, arguments, source="real", is_error=True, result=repr(e)
                    )
                )
            return _error_content(f"backend error: {e!r}")
        if self.trace_sink is not None:
            self.trace_sink.record(
                TraceEntry(
                    name,
                    arguments,
                    source="real",
                    is_error=result.isError,
                    result=list(result.content),
                )
            )
        return list(result.content)

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
            ) -> list[types.ContentBlock]:
                return await self.call_tool(name, arguments)

            self._server = server
        return self._server


def _to_content(value: Any) -> list[types.ContentBlock]:
    """把 mock 值转成 ContentBlock 列表（统一 TextContent）。"""
    if isinstance(value, list):
        return value
    return [types.TextContent(type="text", text=str(value))]


def _error_content(msg: str) -> list[types.ContentBlock]:
    """构造错误文本（骨架；后续用 CallToolResult(isError=True) 表达）。"""
    return [types.TextContent(type="text", text=f"[proxy error] {msg}")]
