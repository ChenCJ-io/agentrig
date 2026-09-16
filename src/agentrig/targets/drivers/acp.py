"""Agent Client Protocol (ACP) stdio 被测 Agent Driver。"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import acp
from acp import schema as acp_schema

from ...identifiers import new_id
from ..driver_schemas import AcpTargetOptions
from .base import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverSession,
    ToolCall,
    ToolResult,
)


class _AcpClient:
    """AgentRig 在 ACP 连接中的最小 Client 实现。"""

    def __init__(self, *, permission_mode: str) -> None:
        self._permission_mode = permission_mode
        self._updates: asyncio.Queue[tuple[Any, float]] = asyncio.Queue()

    async def session_update(
        self,
        session_id: str,
        update: Any,
        **kwargs: Any,
    ) -> None:
        del session_id, kwargs
        await self._updates.put((update, time.monotonic()))

    async def request_permission(
        self,
        session_id: str,
        tool_call: Any,
        options: list[acp_schema.PermissionOption],
        **kwargs: Any,
    ) -> acp_schema.RequestPermissionResponse:
        del session_id, tool_call, kwargs
        if self._permission_mode == "allow_once":
            selected = next(
                (item for item in options if item.kind == "allow_once"),
                None,
            )
            if selected is not None:
                return acp_schema.RequestPermissionResponse(
                    outcome=acp_schema.AllowedOutcome(
                        outcome="selected",
                        option_id=selected.option_id,
                    )
                )
        return acp_schema.RequestPermissionResponse(
            outcome=acp_schema.DeniedOutcome(outcome="cancelled")
        )

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> acp_schema.ReadTextFileResponse:
        del session_id, path, line, limit, kwargs
        raise PermissionError("AgentRig ACP client does not expose host file reads")

    async def write_text_file(
        self,
        session_id: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        del session_id, path, content, kwargs
        raise PermissionError("AgentRig ACP client does not expose host file writes")

    def reset_updates(self) -> None:
        while not self._updates.empty():
            with suppress(asyncio.QueueEmpty):
                self._updates.get_nowait()

    async def next_update(self) -> tuple[Any, float]:
        return await self._updates.get()

    def drain_updates(self) -> list[tuple[Any, float]]:
        values: list[tuple[Any, float]] = []
        while not self._updates.empty():
            with suppress(asyncio.QueueEmpty):
                values.append(self._updates.get_nowait())
        return values


class AcpDriver:
    """启动一个 stdio ACP Agent，并把会话更新归一为 AgentRig 事件。"""

    def __init__(self, *, executable_allowlist: list[str]) -> None:
        self._allowlist = {
            Path(value).expanduser().resolve() for value in executable_allowlist
        }

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=False,
            session_resume=True,
            usage_metrics=True,
            tool_proxy_injection=True,
        )

    def validate_configuration(
        self,
        options: dict[str, Any],
        *,
        secret_configured: bool,
    ) -> None:
        """静态检查 ACP 启动配置，不启动进程或模型。"""

        parsed = AcpTargetOptions.model_validate(options)
        if any(not item.strip() for item in parsed.command):
            raise ValueError("acp target options.command items must be non-empty strings")

        cwd = self._resolved_cwd(parsed.cwd)
        if parsed.cwd is not None and not cwd.is_dir():
            raise ValueError(f"acp target cwd is not a directory: {cwd}")
        executable = self._resolved_executable(parsed.command[0], cwd=cwd)
        if executable not in self._allowlist:
            raise PermissionError(
                "ACP executable is not permitted by deployment "
                f"subprocess_allowlist: {executable}"
            )
        if not executable.is_file():
            raise ValueError(f"ACP executable does not exist: {executable}")
        if not os.access(executable, os.X_OK):
            raise PermissionError(f"ACP executable is not executable: {executable}")

        if parsed.credential_env is not None:
            self._validate_env_name(parsed.credential_env, field="credential_env")
            if not secret_configured:
                raise ValueError(
                    "acp target credential_env requires target secret_ref"
                )
        elif secret_configured:
            raise ValueError(
                "acp target secret_ref requires options.credential_env"
            )
        for name in parsed.env:
            self._validate_env_name(name, field="env")

        has_isolation_root = parsed.isolation_root is not None
        has_isolation_env = parsed.isolation_env is not None
        if has_isolation_root != has_isolation_env:
            raise ValueError(
                "acp target isolation_root and isolation_env must be configured together"
            )
        if parsed.isolation_env is not None:
            self._validate_env_name(parsed.isolation_env, field="isolation_env")

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        options = dict(context.target.get("options") or {})
        self.validate_configuration(
            options,
            secret_configured=context.secret_value is not None,
        )
        parsed = AcpTargetOptions.model_validate(options)
        arguments = parsed.command
        executable = arguments[0]
        permission_mode = parsed.permission_mode
        client = _AcpClient(permission_mode=permission_mode)
        environment = dict(parsed.env)
        credential_env = parsed.credential_env
        if credential_env is not None:
            assert context.secret_value is not None
            environment[credential_env] = context.secret_value

        shutdown_timeout = float(options.get("shutdown_timeout_seconds") or 2.0)
        isolation_dir = self._prepare_isolation_dir(context, options, environment)
        manager: Any | None = None
        entered = False
        stderr_task: asyncio.Task[None] | None = None
        try:
            manager = acp.spawn_agent_process(
                cast(acp.Client, client),
                executable,
                *arguments[1:],
                env=environment,
                cwd=parsed.cwd,
                transport_kwargs={"shutdown_timeout": shutdown_timeout},
            )
            connection, process = await manager.__aenter__()
            entered = True
            if process.stderr is not None:
                stderr_task = asyncio.create_task(self._drain_stderr(process.stderr))
            async with asyncio.timeout(context.component_timeout_seconds):
                initialized = await connection.initialize(
                    protocol_version=acp.PROTOCOL_VERSION,
                    client_capabilities=acp_schema.ClientCapabilities(),
                    client_info=acp_schema.Implementation(
                        name="agentrig",
                        title="AgentRig",
                        version="0.1.0",
                    ),
                )
                mcp_servers: list[
                    acp_schema.HttpMcpServer
                    | acp_schema.SseMcpServer
                    | acp_schema.AcpMcpServer
                    | acp_schema.McpServerStdio
                ] = []
                if context.tool_proxy_url:
                    capabilities = initialized.agent_capabilities
                    mcp_capabilities = (
                        capabilities.mcp_capabilities
                        if capabilities is not None
                        else None
                    )
                    if mcp_capabilities is None or not mcp_capabilities.http:
                        raise RuntimeError(
                            "ACP agent does not support Streamable HTTP MCP servers"
                        )
                    mcp_servers.append(
                        acp_schema.HttpMcpServer(
                            type="http",
                            name=str(
                                options.get("mcp_server_name")
                                or "agentrig-case-tools"
                            ),
                            url=context.tool_proxy_url,
                            headers=[
                                acp_schema.HttpHeader(name=name, value=value)
                                for name, value in context.tool_proxy_headers.items()
                            ],
                        )
                    )
                created = await connection.new_session(
                    cwd=str(options.get("session_cwd") or "/workspace"),
                    mcp_servers=mcp_servers,
                )
        except Exception:
            try:
                if entered and manager is not None:
                    await manager.__aexit__(None, None, None)
            finally:
                if stderr_task is not None:
                    await self._finish_stderr_task(stderr_task)
                self._cleanup_isolation_dir(isolation_dir)
            raise

        assert manager is not None
        return DriverSession(
            id=created.session_id,
            state={
                "connection": connection,
                "process_manager": manager,
                "client": client,
                "stderr_task": stderr_task,
                "session_announced": False,
                "closed": False,
                "isolation_dir": isolation_dir,
                "shutdown_timeout_seconds": shutdown_timeout,
            },
        )

    async def probe(self, context: DriverPrepareContext) -> None:
        """完成 ACP initialize/session/new/close，不向模型发送 prompt。"""

        session = await self.prepare(context)
        await self.close(session)

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        connection: acp.ClientSideConnection = session.state["connection"]
        client: _AcpClient = session.state["client"]
        request_id = new_id("request")
        started = time.monotonic()
        yield DriverEvent(
            type=DriverEventType.REQUEST_STARTED,
            request_id=request_id,
            request_kind="prompt",
        )
        if not bool(session.state["session_announced"]):
            session.state["session_announced"] = True
            yield DriverEvent(
                type=DriverEventType.SESSION_STARTED,
                session_id=session.id,
                request_id=request_id,
            )

        client.reset_updates()
        prompt_task = asyncio.create_task(
            connection.prompt(
                session_id=str(session.id),
                prompt=[acp.text_block(message)],
            )
        )
        first_visible_at: float | None = None
        try:
            while not prompt_task.done():
                update_task = asyncio.create_task(client.next_update())
                done, _pending = await asyncio.wait(
                    {prompt_task, update_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if update_task in done:
                    update, received_at = update_task.result()
                    if self._is_visible_update(update) and first_visible_at is None:
                        first_visible_at = received_at
                    for event in self._map_update(update, request_id=request_id):
                        yield event
                else:
                    update_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await update_task
            response = await prompt_task
            for update, received_at in client.drain_updates():
                if self._is_visible_update(update) and first_visible_at is None:
                    first_visible_at = received_at
                for event in self._map_update(update, request_id=request_id):
                    yield event
            if response.usage is not None:
                yield DriverEvent(
                    type=DriverEventType.USAGE,
                    request_id=request_id,
                    usage=response.usage.model_dump(mode="json"),
                )
            if response.stop_reason == "refusal":
                yield DriverEvent(
                    type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
                    request_id=request_id,
                    refusal=True,
                )
            duration_ms = (time.monotonic() - started) * 1000
            yield DriverEvent(
                type=DriverEventType.REQUEST_COMPLETED,
                request_id=request_id,
                request_kind="prompt",
                request_status=str(response.stop_reason),
                duration_ms=duration_ms,
                ttft_ms=(
                    (first_visible_at - started) * 1000
                    if first_visible_at is not None
                    else None
                ),
            )
            yield DriverEvent(type=DriverEventType.COMPLETED)
        except Exception as exc:
            if not prompt_task.done():
                prompt_task.cancel()
                with suppress(asyncio.CancelledError):
                    await prompt_task
            yield DriverEvent(
                type=DriverEventType.REQUEST_COMPLETED,
                request_id=request_id,
                request_kind="prompt",
                request_status="failed",
                duration_ms=(time.monotonic() - started) * 1000,
            )
            yield DriverEvent(
                type=DriverEventType.ERROR,
                request_id=request_id,
                error=f"ACP prompt failed: {exc}",
            )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session, results
        yield DriverEvent(
            type=DriverEventType.ERROR,
            error="ACP Driver requires proxy mode for tool result delivery",
        )

    async def cancel(self, session: DriverSession) -> None:
        if bool(session.state.get("closed")):
            return
        connection: acp.ClientSideConnection = session.state["connection"]
        timeout = float(session.state["shutdown_timeout_seconds"])
        with suppress(Exception):
            async with asyncio.timeout(timeout):
                await connection.cancel(session_id=str(session.id))

    async def close(self, session: DriverSession) -> None:
        if bool(session.state.get("closed")):
            return
        session.state["closed"] = True
        connection: acp.ClientSideConnection = session.state["connection"]
        manager: Any = session.state["process_manager"]
        timeout = float(session.state["shutdown_timeout_seconds"])
        with suppress(Exception):
            async with asyncio.timeout(timeout):
                await connection.close_session(session_id=str(session.id))
        try:
            await manager.__aexit__(None, None, None)
        finally:
            stderr_task: asyncio.Task[None] | None = session.state.get(
                "stderr_task"
            )
            if stderr_task is not None:
                await self._finish_stderr_task(stderr_task)
            self._cleanup_isolation_dir(
                cast(Path | None, session.state.get("isolation_dir"))
            )

    @staticmethod
    def _map_update(update: Any, *, request_id: str) -> list[DriverEvent]:
        if isinstance(update, acp_schema.AgentMessageChunk):
            content = update.content
            if isinstance(content, acp_schema.TextContentBlock):
                return [
                    DriverEvent(
                        type=DriverEventType.ASSISTANT_TEXT_DELTA,
                        request_id=request_id,
                        text=content.text,
                    )
                ]
        if isinstance(update, acp_schema.ToolCallStart):
            return [
                DriverEvent(
                    type=DriverEventType.TOOL_CALLS,
                    request_id=request_id,
                    tool_calls=[
                        ToolCall(
                            id=update.tool_call_id,
                            name=update.title,
                            arguments=(
                                dict(update.raw_input)
                                if isinstance(update.raw_input, dict)
                                else {}
                            ),
                        )
                    ],
                )
            ]
        return []

    @staticmethod
    def _is_visible_update(update: Any) -> bool:
        return isinstance(
            update,
            (acp_schema.AgentMessageChunk, acp_schema.ToolCallStart),
        )

    @staticmethod
    def _prepare_isolation_dir(
        context: DriverPrepareContext,
        options: dict[str, Any],
        environment: dict[str, str],
    ) -> Path | None:
        isolation_root_value = options.get("isolation_root")
        if isolation_root_value is None:
            return None
        isolation_env = options.get("isolation_env")
        if not isinstance(isolation_env, str) or not isolation_env:
            raise ValueError(
                "acp target isolation_root requires a non-empty isolation_env"
            )
        root = Path(str(isolation_root_value)).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        isolation_dir = (root / context.case_run_id).resolve()
        if isolation_dir.parent != root:
            raise ValueError("acp case directory escaped isolation_root")
        isolation_dir.mkdir(parents=False, exist_ok=False)
        environment[isolation_env] = str(isolation_dir)
        return isolation_dir

    @staticmethod
    def _resolved_cwd(value: str | None) -> Path:
        return (
            Path(value).expanduser().resolve()
            if value is not None
            else Path.cwd().resolve()
        )

    @staticmethod
    def _resolved_executable(value: str, *, cwd: Path) -> Path:
        executable = Path(value).expanduser()
        return (
            executable.resolve()
            if executable.is_absolute()
            else (cwd / executable).resolve()
        )

    @staticmethod
    def _validate_env_name(value: str, *, field: str) -> None:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
            raise ValueError(
                f"acp target {field} contains an invalid environment variable name: "
                f"{value}"
            )

    @staticmethod
    def _cleanup_isolation_dir(isolation_dir: Path | None) -> None:
        if isolation_dir is not None and isolation_dir.is_dir():
            shutil.rmtree(isolation_dir)

    @staticmethod
    async def _drain_stderr(reader: asyncio.StreamReader) -> None:
        while await reader.readline():
            pass

    @staticmethod
    async def _finish_stderr_task(task: asyncio.Task[None]) -> None:
        if task.done():
            with suppress(asyncio.CancelledError, Exception):
                await task
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
