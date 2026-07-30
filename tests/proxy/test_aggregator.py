"""V1 MCP Proxy 的工具聚合和 CaseRun Scope 测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp import types

from agentrig.proxy import NAMESPACE_SEP, AgentRigProxy, BackendRegistry
from agentrig.targets.drivers import ToolResult


@dataclass
class _FakeListResult:
    tools: list[types.Tool]


@dataclass
class _FakeBackendSession:
    tools: list[types.Tool]

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(self.tools)


def _tool(name: str) -> types.Tool:
    return types.Tool(name=name, description=name, inputSchema={})


async def test_list_tools_aggregates_with_namespace() -> None:
    registry = BackendRegistry()
    registry.add("fs", _FakeBackendSession(tools=[_tool("read")]))
    registry.add("git", _FakeBackendSession(tools=[_tool("commit")]))

    tools = await AgentRigProxy(registry).list_tools()

    assert {tool.name for tool in tools} == {
        f"fs{NAMESPACE_SEP}read",
        f"git{NAMESPACE_SEP}commit",
    }


async def test_call_without_case_scope_is_rejected(
    monkeypatch: Any,
) -> None:
    proxy = AgentRigProxy(BackendRegistry())
    monkeypatch.setattr(proxy, "_scope_token", lambda: None)

    result = await proxy.call_tool("fs__read", {"path": "/tmp/a"})

    assert result.isError is True
    assert "header is required" in result.content[0].text


async def test_scoped_call_uses_case_provider_and_preserves_output_schema(
    monkeypatch: Any,
) -> None:
    class Scope:
        async def resolve(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            result_schema: dict[str, Any] | None,
        ) -> ToolResult:
            assert name == "fs__read"
            assert arguments == {"path": "/tmp/a"}
            assert result_schema == {"type": "object"}
            return ToolResult(
                tool_call_id="call_1",
                tool_name=name,
                result={"source": "case-scope"},
                source="fixture",
            )

    class Scopes:
        def get(self, token: str) -> Scope | None:
            return Scope() if token == "scope-token" else None

    registry = BackendRegistry()
    registry.add(
        "fs",
        _FakeBackendSession(
            tools=[
                types.Tool(
                    name="read",
                    description="read",
                    inputSchema={},
                    outputSchema={"type": "object"},
                )
            ]
        ),
    )
    proxy = AgentRigProxy(
        registry,
        scope_registry=Scopes(),  # type: ignore[arg-type]
    )
    await proxy.list_tools()
    monkeypatch.setattr(proxy, "_scope_token", lambda: "scope-token")

    result = await proxy.call_tool("fs__read", {"path": "/tmp/a"})

    assert result.isError is False
    assert result.structuredContent == {"source": "case-scope"}
