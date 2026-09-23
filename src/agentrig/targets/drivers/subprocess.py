"""实验性本地 JSONL subprocess Driver。"""

from __future__ import annotations

import asyncio
import hashlib
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

# 单行协议上限：工具参数、描述和完整回复都可能远超 asyncio 默认的 64 KiB。
_STREAM_LIMIT = 8 * 1_024 * 1_024
_STDERR_TAIL_BYTES = 16 * 1_024


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
        self._require_allowlisted(str(command[0]))
        environment = os.environ.copy()
        environment.update(
            {
                str(key): str(value)
                for key, value in dict(options.get("env") or {}).items()
            }
        )
        session = await self._spawn(
            [str(item) for item in command],
            cwd=options.get("cwd"),
            env=environment,
        )
        session.state.update(
            {
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
        return session

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        async for event in self._exchange(session, self._chat_payload(session, message)):
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
        drain: asyncio.Task[None] | None = session.state.get("stderr_drain")
        if drain is not None and not drain.done():
            drain.cancel()

    def _require_allowlisted(self, executable: str) -> None:
        if executable not in self._allowlist:
            raise PermissionError("subprocess executable is not in the deployment allowlist")

    async def _spawn(
        self,
        command: list[str],
        *,
        cwd: str | None,
        env: dict[str, str],
    ) -> DriverSession:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
        stderr_tail = bytearray()
        drain = (
            asyncio.create_task(_drain_stderr(process.stderr, stderr_tail))
            if process.stderr is not None
            else None
        )
        return DriverSession(
            state={"process": process, "stderr_tail": stderr_tail, "stderr_drain": drain}
        )

    def _chat_payload(self, session: DriverSession, message: str) -> dict[str, Any]:
        return {
            "type": "chat",
            "message": message,
            "version": session.state.get("version"),
            "initial_state": session.state.get("initial_state"),
            "tool_proxy": session.state.get("tool_proxy"),
        }

    def _stops_at_tool_calls(self, session: DriverSession) -> bool:
        """tool_calls 是否表示等待结果回灌；只观察的子进程会自己执行工具并继续输出。"""

        del session
        return True

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
        terminal = {DriverEventType.COMPLETED, DriverEventType.ERROR}
        if self._stops_at_tool_calls(session):
            terminal.add(DriverEventType.TOOL_CALLS)
        while True:
            raw = await process.stdout.readline()
            if not raw:
                yield DriverEvent(
                    type=DriverEventType.ERROR,
                    error=f"subprocess exited unexpectedly: {await self._stderr_tail(session)}",
                )
                return
            try:
                event = self._event(json.loads(raw))
            except (KeyError, TypeError, ValueError) as exc:
                line = raw.decode("utf-8", errors="replace").strip()
                yield DriverEvent(
                    type=DriverEventType.ERROR,
                    error=f"subprocess emitted an invalid protocol line ({exc}): {line[:200]}",
                )
                return
            yield event
            if event.type in terminal:
                return

    async def _stderr_tail(self, session: DriverSession) -> str:
        drain: asyncio.Task[None] | None = session.state.get("stderr_drain")
        if drain is not None:
            try:
                await asyncio.wait_for(asyncio.shield(drain), timeout=1)
            except TimeoutError:
                pass
        tail = session.state.get("stderr_tail") or b""
        return bytes(tail).decode("utf-8", errors="replace")

    @staticmethod
    def _event(value: dict[str, Any]) -> DriverEvent:
        event_type = DriverEventType(value["type"])
        payload = dict(value.get("payload") or {})
        if event_type is DriverEventType.TOOL_RESULT_OBSERVED:
            payload = _observed_result_digest(payload)
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
            payload=payload,
        )


async def _drain_stderr(stream: asyncio.StreamReader, tail: bytearray) -> None:
    """持续读取 stderr 并只保留末尾，避免日志写满管道后子进程阻塞。"""

    while chunk := await stream.read(4_096):
        tail.extend(chunk)
        del tail[:-_STDERR_TAIL_BYTES]


def _observed_result_digest(payload: dict[str, Any]) -> dict[str, Any]:
    """与 AG-UI Driver 一致：观察到的工具结果默认只保留摘要，不导出正文。"""

    if "result" not in payload:
        return payload
    result = payload.pop("result")
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode(
        "utf-8"
    )
    return {
        **payload,
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "result_exported": False,
    }
