"""Harness 运行时：协议通道、挂起的工具调用与当前回合上下文。

本模块运行在被测 Agent 自己的解释器里：只依赖标准库，并保持 Python 3.10 兼容。
"""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import json
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import IO, Any

PROTOCOL = "agentrig.harness.v1"
CONTROLLED = "controlled"


class HarnessClosedError(RuntimeError):
    """AgentRig 在工具调用等待结果时关闭了通道。"""


@dataclass(frozen=True)
class HarnessContext:
    """当前 CaseRun 回合的只读上下文，被测代码可以通过 ``agentrig.sdk.current()`` 读取。"""

    case_run_id: str | None = None
    version: str | None = None
    initial_state: dict[str, Any] = field(default_factory=dict)
    tool_mode: str = CONTROLLED
    turn: int = 0


class HarnessRuntime:
    """同一 harness 进程内所有工具拦截点共享的调用桥。

    受控模式下工具调用发给 AgentRig，阻塞到结果回灌，原函数不执行；其他模式下真实执行并
    上报结果。协议行和挂起调用可能来自框架的工作线程，所以写入与登记都加锁。
    """

    def __init__(self, output: IO[str]) -> None:
        self.context = HarnessContext()
        self._output = output
        self._write_lock = threading.Lock()
        self._pending: dict[str, Future[Any]] = {}
        self._pending_lock = threading.Lock()
        self._sequence = itertools.count(1)
        self._closed = False

    def emit(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, default=_json_fallback)
        with self._write_lock:
            self._output.write(line + "\n")
            self._output.flush()

    def intercept(
        self,
        name: str,
        arguments: dict[str, Any],
        execute: Callable[[], Any],
        *,
        call_id: str | None = None,
        result_schema: dict[str, Any] | None = None,
    ) -> Any:
        """同步拦截一次工具调用。"""

        if self.context.tool_mode == CONTROLLED:
            return self._request(name, arguments, call_id, result_schema).result()
        identifier = self._announce(name, arguments, call_id, None)
        try:
            value = execute()
        except Exception as exc:
            self._report(identifier, name, error=exc)
            raise
        self._report(identifier, name, result=value)
        return value

    async def aintercept(
        self,
        name: str,
        arguments: dict[str, Any],
        execute: Callable[[], Awaitable[Any]],
        *,
        call_id: str | None = None,
        result_schema: dict[str, Any] | None = None,
    ) -> Any:
        """异步拦截一次工具调用；等待结果时不阻塞事件循环。"""

        if self.context.tool_mode == CONTROLLED:
            future = self._request(name, arguments, call_id, result_schema)
            return await asyncio.wrap_future(future)
        identifier = self._announce(name, arguments, call_id, None)
        try:
            value = await execute()
        except Exception as exc:
            self._report(identifier, name, error=exc)
            raise
        self._report(identifier, name, result=value)
        return value

    def resolve(self, results: list[Any]) -> None:
        """把 AgentRig 回灌的 ToolResult 交给对应的挂起调用。"""

        for item in results:
            if not isinstance(item, dict):
                continue
            with self._pending_lock:
                future = self._pending.pop(str(item.get("tool_call_id") or ""), None)
            if future is not None and not future.done():
                future.set_result(item.get("result"))

    def close(self) -> None:
        with self._pending_lock:
            self._closed = True
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(
                    HarnessClosedError("AgentRig closed the harness channel")
                )

    def _request(
        self,
        name: str,
        arguments: dict[str, Any],
        call_id: str | None,
        result_schema: dict[str, Any] | None,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        with self._pending_lock:
            if self._closed:
                raise HarnessClosedError("AgentRig closed the harness channel")
            identifier = self._unique_id(call_id)
            self._pending[identifier] = future
        self._emit_call(identifier, name, arguments, result_schema)
        return future

    def _announce(
        self,
        name: str,
        arguments: dict[str, Any],
        call_id: str | None,
        result_schema: dict[str, Any] | None,
    ) -> str:
        with self._pending_lock:
            identifier = self._unique_id(call_id)
        self._emit_call(identifier, name, arguments, result_schema)
        return identifier

    def _emit_call(
        self,
        identifier: str,
        name: str,
        arguments: dict[str, Any],
        result_schema: dict[str, Any] | None,
    ) -> None:
        call: dict[str, Any] = {
            "id": identifier,
            "name": name,
            "arguments": jsonable(arguments) if isinstance(arguments, dict) else {},
        }
        if result_schema is not None:
            call["result_schema"] = result_schema
        self.emit({"type": "tool_calls", "tool_calls": [call]})

    def _report(
        self,
        identifier: str,
        name: str,
        *,
        result: Any = None,
        error: BaseException | None = None,
    ) -> None:
        payload: dict[str, Any] = {"tool_call_id": identifier, "tool_name": name}
        if error is not None:
            payload["error"] = f"{type(error).__name__}: {error}"
        else:
            payload["result"] = jsonable(result)
        self.emit({"type": "tool_result_observed", "payload": payload})

    def _unique_id(self, call_id: str | None) -> str:
        # 调用方持有 _pending_lock。框架给出的 id 可能在不同回合重复，冲突时追加序号。
        identifier = call_id or f"call_{next(self._sequence)}"
        if identifier in self._pending:
            identifier = f"{identifier}_{next(self._sequence)}"
        return identifier


def jsonable(value: Any) -> Any:
    """转换成可写入协议的 JSON 值；无法表示的对象退化为 repr。"""

    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_fallback))


def _json_fallback(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return repr(value)


_active: HarnessRuntime | None = None


def activate(runtime: HarnessRuntime | None) -> None:
    global _active
    _active = runtime


def active_runtime() -> HarnessRuntime | None:
    return _active


def current() -> HarnessContext | None:
    """在 AgentRig harness 中运行时返回当前回合上下文，否则返回 ``None``。"""

    runtime = _active
    return None if runtime is None else runtime.context
