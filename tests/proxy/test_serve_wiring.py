"""serve 接线测试：runtime 单例提供 mock hub + trace，被 AgentRigProxy 使用。

验证 Phase B 的核心：proxy 在 serve 模式下真正 mock + 录 trace（不再纯透传），
且 execution / sampling 能通过 get_runtime() 拿到同一组实例。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp import types

from agentrig.mock import ToolMockHub
from agentrig.proxy import NAMESPACE_SEP, BackendRegistry, TraceSink
from agentrig.proxy.aggregator import AgentRigProxy
from agentrig.runtime import Runtime, get_runtime, reset_runtime


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
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(self.tools)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> _FakeCallResult:
        self.calls.append((name, arguments or {}))
        return _FakeCallResult(content=[types.TextContent(type="text", text=f"real:{name}")])


def _tool(name: str) -> types.Tool:
    return types.Tool(name=name, description=name, inputSchema={})


async def test_runtime_wires_hub_and_trace_into_proxy() -> None:
    """runtime 的 hub/trace 注入 proxy：mock 命中走 hub，trace 同时记录 mock 与 real。"""
    reset_runtime()
    rt = get_runtime()
    assert isinstance(rt.hub, ToolMockHub)
    assert isinstance(rt.trace, TraceSink)
    assert isinstance(rt.registry, BackendRegistry)

    rt.registry.add("echo", _FakeBackendSession(tools=[_tool("echo"), _tool("reverse")]))
    proxy = AgentRigProxy(rt.registry, mock_policy=rt.hub, trace_sink=rt.trace)

    # mock 命中：hub 设 inline，不转发后端
    rt.hub.set_inline(f"echo{NAMESPACE_SEP}echo", "mocked!")
    content = await proxy.call_tool(f"echo{NAMESPACE_SEP}echo", {"text": "hi"})
    assert content[0].text == "mocked!"

    # real：清 inline 后转发 fake 后端
    rt.hub.clear_inline()
    content = await proxy.call_tool(f"echo{NAMESPACE_SEP}reverse", {"text": "hi"})
    assert content[0].text == "real:reverse"

    # trace 同时记录了 mock 与 real
    sources = [e.source for e in rt.trace.entries]
    assert sources == ["mock", "real"]

    reset_runtime()


def test_runtime_singleton_is_stable() -> None:
    """get_runtime 多次调用返回同一实例（进程级单例）。"""
    reset_runtime()
    rt1 = get_runtime()
    rt2 = get_runtime()
    assert rt1 is rt2
    reset_runtime()


def test_reset_runtime_clears_singleton() -> None:
    """reset_runtime() 后 get_runtime 建新实例。"""
    reset_runtime()
    rt1 = get_runtime()
    reset_runtime()  # 清空
    rt2 = get_runtime()
    assert rt1 is not rt2
    reset_runtime()


def test_runtime_inject_custom() -> None:
    """reset_runtime(rt) 注入自定义实例，get_runtime 返回它。"""
    custom = Runtime(hub=ToolMockHub(), trace=TraceSink(), registry=BackendRegistry())
    reset_runtime(custom)
    assert get_runtime() is custom
    reset_runtime()
