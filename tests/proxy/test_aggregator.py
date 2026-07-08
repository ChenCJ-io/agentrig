"""AgentRigProxy 单元测试：聚合 + 路由转发 + mock 注入 + trace（用 stub 后端）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp import types

from agentrig.proxy import (
    NAMESPACE_SEP,
    AgentRigProxy,
    BackendRegistry,
    StaticMockPolicy,
    TraceSink,
)


@dataclass
class _FakeListResult:
    """stub for mcp ListToolsResult。"""

    tools: list[types.Tool]


@dataclass
class _FakeCallResult:
    """stub for mcp CallToolResult。"""

    content: list[types.TextContent]
    isError: bool = False


@dataclass
class _FakeBackendSession:
    """stub 后端 ClientSession：记录调用并返回预设。"""

    tools: list[types.Tool]
    results: dict[str, Any] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(self.tools)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> _FakeCallResult:
        self.calls.append((name, arguments or {}))
        if name in self.results:
            r = self.results[name]
            if isinstance(r, list):
                return _FakeCallResult(content=r)
            return _FakeCallResult(content=[types.TextContent(type="text", text=str(r))])
        return _FakeCallResult(content=[types.TextContent(type="text", text=f"ok:{name}")])


def _tool(name: str) -> types.Tool:
    return types.Tool(name=name, description=name, inputSchema={})


async def test_list_tools_aggregates_with_namespace() -> None:
    """多个后端工具应聚合，且加 namespace 前缀防撞名。"""
    fs = _FakeBackendSession(tools=[_tool("read")])
    git = _FakeBackendSession(tools=[_tool("commit")])
    reg = BackendRegistry()
    reg.add("fs", fs)
    reg.add("git", git)

    proxy = AgentRigProxy(reg)
    tools = await proxy.list_tools()
    assert {t.name for t in tools} == {
        f"fs{NAMESPACE_SEP}read",
        f"git{NAMESPACE_SEP}commit",
    }


async def test_call_tool_forwards_to_backend() -> None:
    """无 mock 时，按命名空间路由转发到对应后端。"""
    fs = _FakeBackendSession(tools=[_tool("read")], results={"read": "hello"})
    reg = BackendRegistry()
    reg.add("fs", fs)

    proxy = AgentRigProxy(reg)
    content = await proxy.call_tool(f"fs{NAMESPACE_SEP}read", {"path": "/x"})
    assert content[0].text == "hello"
    assert fs.calls == [("read", {"path": "/x"})]


async def test_mock_intercepts_before_forwarding() -> None:
    """mock 命中时直接返回预设，不转发后端。"""
    fs = _FakeBackendSession(tools=[_tool("read")])
    reg = BackendRegistry()
    reg.add("fs", fs)

    mock = StaticMockPolicy({f"fs{NAMESPACE_SEP}read": "mocked!"})
    proxy = AgentRigProxy(reg, mock_policy=mock)
    content = await proxy.call_tool(f"fs{NAMESPACE_SEP}read", {"path": "/x"})
    assert content[0].text == "mocked!"
    assert fs.calls == []  # 未转发


async def test_trace_records_mock_and_real() -> None:
    """trace 应区分 mock / real 来源，并记录后端 isError。"""
    fs = _FakeBackendSession(
        tools=[_tool("read"), _tool("write")],
        results={"write": "done"},
    )
    reg = BackendRegistry()
    reg.add("fs", fs)

    trace = TraceSink()
    mock = StaticMockPolicy({f"fs{NAMESPACE_SEP}read": "mocked"})
    proxy = AgentRigProxy(reg, mock_policy=mock, trace_sink=trace)

    await proxy.call_tool(f"fs{NAMESPACE_SEP}read", {})
    await proxy.call_tool(f"fs{NAMESPACE_SEP}write", {"path": "/y"})

    assert len(trace.entries) == 2
    assert trace.entries[0].source == "mock"
    assert trace.entries[1].source == "real"
    assert trace.entries[1].is_error is False


async def test_unknown_backend_returns_error_text() -> None:
    """未知后端应返回错误文本（第一周骨架表达，不抛异常）。"""
    reg = BackendRegistry()
    proxy = AgentRigProxy(reg)
    content = await proxy.call_tool("unknown__tool", {})
    assert content[0].text.startswith("[proxy error]")
