"""正式 ACP Driver 的会话、MCP 注入和生命周期契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from acp import schema as acp_schema

from agentrig.targets.drivers import (
    AcpDriver,
    DriverEventType,
    DriverPrepareContext,
)


def _make_executable(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o700)
    return str(path)


class _FakeConnection:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.mcp_servers: list[Any] = []
        self.closed_session: str | None = None
        self.cancelled_session: str | None = None

    async def initialize(self, **kwargs: Any) -> Any:
        assert kwargs["protocol_version"] == 1
        return SimpleNamespace(
            agent_capabilities=SimpleNamespace(
                mcp_capabilities=SimpleNamespace(http=True)
            )
        )

    async def new_session(self, **kwargs: Any) -> Any:
        assert kwargs["cwd"] == "/workspace"
        self.mcp_servers = kwargs["mcp_servers"]
        return SimpleNamespace(session_id="acp-session-1")

    async def prompt(self, **kwargs: Any) -> Any:
        assert kwargs["session_id"] == "acp-session-1"
        assert kwargs["prompt"][0].text == "hello"
        await self.client.session_update(
            "acp-session-1",
            acp_schema.AgentThoughtChunk(
                sessionUpdate="agent_thought_chunk",
                content=acp_schema.TextContentBlock(type="text", text="thinking"),
            ),
        )
        await self.client.session_update(
            "acp-session-1",
            acp_schema.ToolCallStart(
                sessionUpdate="tool_call",
                toolCallId="call-weather",
                title="get_weather",
                rawInput={"city": "Shanghai"},
            ),
        )
        await self.client.session_update(
            "acp-session-1",
            acp_schema.AgentMessageChunk(
                sessionUpdate="agent_message_chunk",
                content=acp_schema.TextContentBlock(type="text", text="ACP "),
            ),
        )
        await self.client.session_update(
            "acp-session-1",
            acp_schema.AgentMessageChunk(
                sessionUpdate="agent_message_chunk",
                content=acp_schema.TextContentBlock(type="text", text="OK"),
            ),
        )
        return SimpleNamespace(
            usage=acp_schema.Usage(
                totalTokens=12,
                inputTokens=10,
                outputTokens=2,
            ),
            stop_reason="end_turn",
        )

    async def close_session(self, *, session_id: str) -> None:
        self.closed_session = session_id

    async def cancel(self, *, session_id: str) -> None:
        self.cancelled_session = session_id


class _FakeManager:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.exited = False
        self.raise_on_exit = False
        self.process = SimpleNamespace(stderr=None)

    async def __aenter__(self) -> tuple[_FakeConnection, Any]:
        return self.connection, self.process

    async def __aexit__(self, *args: Any) -> None:
        del args
        self.exited = True
        if self.raise_on_exit:
            raise RuntimeError("process shutdown failed")


async def test_acp_driver_injects_proxy_and_normalizes_session_updates(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def spawn(client: Any, command: str, *args: str, **kwargs: Any) -> _FakeManager:
        captured.update(
            {
                "command": command,
                "args": args,
                "env": kwargs["env"],
                "cwd": kwargs["cwd"],
            }
        )
        manager = _FakeManager(_FakeConnection(client))
        captured["manager"] = manager
        return manager

    monkeypatch.setattr(
        "agentrig.targets.drivers.acp.acp.spawn_agent_process",
        spawn,
    )
    goose_root = tmp_path / "goose"
    executable = _make_executable(goose_root / "run-acp.sh")
    isolation_root = tmp_path / "case-runtimes"
    driver = AcpDriver(executable_allowlist=[executable])
    session = await driver.prepare(
        DriverPrepareContext(
            case_run_id="case_run_acp",
            target={
                "options": {
                    "command": [executable, "--test"],
                    "cwd": str(goose_root),
                    "session_cwd": "/workspace",
                    "credential_env": "DEEPSEEK_API_KEY",
                    "env": {
                        "GOOSE_PROVIDER": "custom_deepseek",
                        "GOOSE_MODEL": "deepseek-v4-flash",
                    },
                    "isolation_root": str(isolation_root),
                    "isolation_env": "GOOSE_RUNTIME_DIR",
                }
            },
            version="deepseek-v4-flash",
            secret_value="test-secret",
            component_timeout_seconds=5,
            tool_proxy_url="http://host.docker.internal:8010/proxy",
            tool_proxy_headers={"X-AgentRig-Proxy-Scope": "scope-1"},
        )
    )
    events = [event async for event in driver.send_user_message(session, "hello")]

    assert session.id == "acp-session-1"
    assert captured["command"] == executable
    assert captured["args"] == ("--test",)
    assert captured["env"]["DEEPSEEK_API_KEY"] == "test-secret"
    assert captured["cwd"] == str(goose_root)
    assert Path(captured["env"]["GOOSE_RUNTIME_DIR"]).is_dir()
    assert [event.type for event in events] == [
        DriverEventType.REQUEST_STARTED,
        DriverEventType.SESSION_STARTED,
        DriverEventType.TOOL_CALLS,
        DriverEventType.ASSISTANT_TEXT_DELTA,
        DriverEventType.ASSISTANT_TEXT_DELTA,
        DriverEventType.USAGE,
        DriverEventType.REQUEST_COMPLETED,
        DriverEventType.COMPLETED,
    ]
    assert "".join(event.text or "" for event in events) == "ACP OK"
    assert events[2].tool_calls[0].arguments == {"city": "Shanghai"}
    assert events[-2].request_status == "end_turn"
    assert events[-2].duration_ms is not None
    assert events[-2].ttft_ms is not None

    manager: _FakeManager = captured["manager"]
    server = manager.connection.mcp_servers[0]
    assert server.url == "http://host.docker.internal:8010/proxy"
    assert [(item.name, item.value) for item in server.headers] == [
        ("X-AgentRig-Proxy-Scope", "scope-1")
    ]

    isolation_dir = Path(captured["env"]["GOOSE_RUNTIME_DIR"])
    await driver.close(session)
    assert manager.connection.closed_session == "acp-session-1"
    assert manager.exited is True
    assert not isolation_dir.exists()


async def test_acp_driver_rejects_non_allowlisted_executable() -> None:
    driver = AcpDriver(executable_allowlist=[])
    context = DriverPrepareContext(
        case_run_id="case_run_acp",
        target={"options": {"command": ["/opt/goose/run-acp.sh"]}},
        version=None,
        component_timeout_seconds=5,
    )

    try:
        await driver.prepare(context)
    except PermissionError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("non-allowlisted ACP executable should be rejected")


async def test_acp_driver_removes_isolation_dir_when_spawn_fails(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    executable = _make_executable(tmp_path / "run-acp.sh")
    isolation_root = tmp_path / "case-runtimes"

    def spawn(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("spawn failed")

    monkeypatch.setattr(
        "agentrig.targets.drivers.acp.acp.spawn_agent_process",
        spawn,
    )
    driver = AcpDriver(executable_allowlist=[executable])
    context = DriverPrepareContext(
        case_run_id="case_run_spawn_failure",
        target={
            "options": {
                "command": [executable],
                "isolation_root": str(isolation_root),
                "isolation_env": "GOOSE_RUNTIME_DIR",
            }
        },
        version=None,
        component_timeout_seconds=5,
    )

    with pytest.raises(RuntimeError, match="spawn failed"):
        await driver.prepare(context)

    assert not (isolation_root / context.case_run_id).exists()


async def test_acp_driver_removes_isolation_dir_when_shutdown_fails(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    captured: dict[str, _FakeManager] = {}
    executable = _make_executable(tmp_path / "run-acp.sh")
    isolation_root = tmp_path / "case-runtimes"

    def spawn(client: Any, *args: Any, **kwargs: Any) -> _FakeManager:
        del args, kwargs
        manager = _FakeManager(_FakeConnection(client))
        captured["manager"] = manager
        return manager

    monkeypatch.setattr(
        "agentrig.targets.drivers.acp.acp.spawn_agent_process",
        spawn,
    )
    driver = AcpDriver(executable_allowlist=[executable])
    session = await driver.prepare(
        DriverPrepareContext(
            case_run_id="case_run_shutdown_failure",
            target={
                "options": {
                    "command": [executable],
                    "isolation_root": str(isolation_root),
                    "isolation_env": "GOOSE_RUNTIME_DIR",
                }
            },
            version=None,
            component_timeout_seconds=5,
        )
    )
    isolation_dir = isolation_root / "case_run_shutdown_failure"
    captured["manager"].raise_on_exit = True

    with pytest.raises(RuntimeError, match="process shutdown failed"):
        await driver.close(session)

    assert not isolation_dir.exists()
