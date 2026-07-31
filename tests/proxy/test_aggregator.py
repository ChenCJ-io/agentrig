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


async def test_fixture_only_scope_exposes_tool_without_real_backend(
    monkeypatch: Any,
) -> None:
    class Scope:
        def declared_tools(self) -> list[dict[str, Any]]:
            return []

        def all_fixtures(self) -> list[dict[str, Any]]:
            return [
                {
                    "tool_name": "get_weather",
                    "match_arguments": {"city": "Shanghai"},
                    "result": {
                        "city": "Shanghai",
                        "temperature": 26,
                    },
                }
            ]

        def current_fixture(self, name: str) -> dict[str, Any] | None:
            return self.all_fixtures()[0] if name == "get_weather" else None

        async def resolve(
            self,
            name: str,
            arguments: dict[str, Any],
            *,
            result_schema: dict[str, Any] | None,
        ) -> ToolResult:
            assert name == "get_weather"
            assert arguments == {"city": "Shanghai"}
            assert result_schema is not None
            assert result_schema["properties"]["temperature"] == {"type": "integer"}
            return ToolResult(
                tool_call_id="call_weather",
                tool_name=name,
                result={"city": "Shanghai", "temperature": 26},
                source="fixture",
            )

    class Scopes:
        def get(self, token: str) -> Scope | None:
            return Scope() if token == "fixture-scope" else None

    proxy = AgentRigProxy(
        BackendRegistry(),
        scope_registry=Scopes(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(proxy, "_scope_token", lambda: "fixture-scope")

    tools = await proxy.list_tools()
    result = await proxy.call_tool("get_weather", {"city": "Shanghai"})

    assert len(tools) == 1
    assert tools[0].name == "get_weather"
    assert tools[0].inputSchema["required"] == ["city"]
    assert result.isError is False
    assert result.structuredContent == {"city": "Shanghai", "temperature": 26}


async def test_scope_exposes_target_declared_tool_catalog(
    monkeypatch: Any,
) -> None:
    class Scope:
        def declared_tools(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "get_exchange_rate",
                    "description": "Return a currency exchange rate",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "base": {"type": "string"},
                            "quote": {"type": "string"},
                        },
                        "required": ["base", "quote"],
                    },
                    "outputSchema": {
                        "type": "object",
                        "properties": {"rate": {"type": "number"}},
                        "required": ["rate"],
                    },
                }
            ]

        def all_fixtures(self) -> list[dict[str, Any]]:
            return []

        def current_fixture(self, name: str) -> None:
            del name

    class Scopes:
        def get(self, token: str) -> Scope | None:
            return Scope() if token == "catalog-scope" else None

    proxy = AgentRigProxy(
        BackendRegistry(),
        scope_registry=Scopes(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(proxy, "_scope_token", lambda: "catalog-scope")

    tools = await proxy.list_tools()

    assert len(tools) == 1
    assert tools[0].name == "get_exchange_rate"
    assert tools[0].outputSchema == {
        "type": "object",
        "properties": {"rate": {"type": "number"}},
        "required": ["rate"],
    }
