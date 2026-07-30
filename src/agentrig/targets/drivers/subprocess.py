"""实验性本地 JSONL subprocess Driver。"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from .base import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverSession,
    ToolCall,
    ToolResult,
)


class SubprocessDriver:
    def __init__(self, *, executable_allowlist: list[str]) -> None:
        self._allowlist = set(executable_allowlist)

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            tool_proxy_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        options = dict(context.target.get("options") or {})
        command = options.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError("subprocess target options.command must be a non-empty list")
        executable = str(command[0])
        if executable not in self._allowlist:
            raise PermissionError("subprocess executable is not in the deployment allowlist")
        environment = os.environ.copy()
        environment.update(
            {
                str(key): str(value)
                for key, value in dict(options.get("env") or {}).items()
            }
        )
        process = await asyncio.create_subprocess_exec(
            *(str(item) for item in command),
            cwd=options.get("cwd"),
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return DriverSession(
            state={
                "process": process,
                "version": context.version,
                "initial_state": context.initial_state,
                "tool_proxy": (
                    {
                        "url": context.tool_proxy_url,
                        "headers": context.tool_proxy_headers,
                    }
                    if context.tool_proxy_url
                    else None
                ),
            }
        )

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        async for event in self._exchange(
            session,
            {
                "type": "chat",
                "message": message,
                "version": session.state.get("version"),
                "initial_state": session.state.get("initial_state"),
                "tool_proxy": session.state.get("tool_proxy"),
            },
        ):
            yield event

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        async for event in self._exchange(
            session,
            {
                "type": "tool_results",
                "results": [item.model_dump(mode="json") for item in results],
            },
        ):
            yield event

    async def cancel(self, session: DriverSession) -> None:
        process: asyncio.subprocess.Process = session.state["process"]
        if process.returncode is None:
            process.terminate()

    async def close(self, session: DriverSession) -> None:
        process: asyncio.subprocess.Process = session.state["process"]
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _exchange(
        self,
        session: DriverSession,
        payload: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        process: asyncio.subprocess.Process = session.state["process"]
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("subprocess pipes are unavailable")
        process.stdin.write(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        )
        await process.stdin.drain()
        while True:
            raw = await process.stdout.readline()
            if not raw:
                stderr = (
                    (await process.stderr.read()).decode("utf-8", errors="replace")
                    if process.stderr is not None
                    else ""
                )
                yield DriverEvent(
                    type=DriverEventType.ERROR,
                    error=f"subprocess exited unexpectedly: {stderr}",
                )
                return
            value = json.loads(raw)
            event = self._event(value)
            yield event
            if event.type in {
                DriverEventType.TOOL_CALLS,
                DriverEventType.COMPLETED,
                DriverEventType.ERROR,
            }:
                return

    @staticmethod
    def _event(value: dict[str, Any]) -> DriverEvent:
        event_type = DriverEventType(value["type"])
        return DriverEvent(
            type=event_type,
            session_id=value.get("session_id"),
            text=value.get("text"),
            refusal=bool(value.get("refusal", False)),
            tool_calls=[
                ToolCall.model_validate(item)
                for item in value.get("tool_calls", [])
            ],
            usage=dict(value.get("usage") or {}),
            error=value.get("error"),
        )
