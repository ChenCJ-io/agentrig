"""``python -m agentrig.sdk.harness --entry module:attribute``

AgentRig 的 ``python_agent`` Driver 在被测 Agent 自己的解释器里启动本进程：stdin 接收
AgentRig 指令，原 stdout 只用于协议行；被测代码的 print 和日志全部改写到 stderr。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import platform
import queue
import sys
import threading
import traceback
from typing import IO, Any

from .. import __version__
from ._runtime import CONTROLLED, PROTOCOL, HarnessContext, HarnessRuntime, activate
from .adapters import ADAPTER_NAMES, Adapter, load_adapter


def main(argv: list[str] | None = None) -> int:
    protocol = _claim_stdout()
    args = _parser().parse_args(argv)
    runtime = HarnessRuntime(protocol)
    activate(runtime)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    adapter: Adapter | None = None
    startup_error: str | None = None
    try:
        adapter = _load(args.entry, adapter=args.adapter, factory=args.factory, loop=loop)
    except Exception as exc:
        traceback.print_exc()
        startup_error = f"harness startup failed: {type(exc).__name__}: {exc}"
    commands: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(
        target=_read_commands,
        args=(runtime, commands),
        name="agentrig-harness-reader",
        daemon=True,
    ).start()
    turn = 0
    try:
        while (command := commands.get()) is not None:
            kind = command.get("type")
            if adapter is None:
                runtime.emit({"type": "error", "error": startup_error})
            elif kind == "describe":
                runtime.emit(_description(adapter))
            elif kind == "chat":
                turn += 1
                _run_turn(runtime, adapter, command, turn=turn, loop=loop)
            else:
                runtime.emit({"type": "error", "error": f"unsupported harness command: {kind}"})
    except (BrokenPipeError, ValueError):
        # AgentRig 已经关闭协议通道；没有人再读取结果，直接退出。
        pass
    finally:
        activate(None)
    return 0


def _run_turn(
    runtime: HarnessRuntime,
    adapter: Adapter,
    command: dict[str, Any],
    *,
    turn: int,
    loop: asyncio.AbstractEventLoop,
) -> None:
    initial_state = command.get("initial_state")
    runtime.context = HarnessContext(
        case_run_id=_optional_text(command.get("case_run_id")),
        version=_optional_text(command.get("version")),
        initial_state=dict(initial_state) if isinstance(initial_state, dict) else {},
        tool_mode=str(command.get("tool_mode") or CONTROLLED),
        turn=turn,
    )
    try:
        output = loop.run_until_complete(
            adapter.run_turn(str(command.get("message") or ""), runtime.context)
        )
    except Exception as exc:
        traceback.print_exc()
        runtime.emit({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        return
    for usage in output.usage:
        runtime.emit({"type": "usage", "usage": usage})
    runtime.emit({"type": "assistant_message_completed", "text": output.text})
    runtime.emit({"type": "completed"})


def _read_commands(
    runtime: HarnessRuntime,
    commands: queue.Queue[dict[str, Any] | None],
) -> None:
    """独立线程读取 stdin，工具结果直接唤醒挂起调用，其他指令交给主线程顺序执行。"""

    try:
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except ValueError:
                print(f"agentrig harness ignored a non-JSON command: {line[:200]}", file=sys.stderr)
                continue
            if not isinstance(value, dict):
                continue
            if value.get("type") == "tool_results":
                results = value.get("results")
                runtime.resolve(results if isinstance(results, list) else [])
            else:
                commands.put(value)
    finally:
        runtime.close()
        commands.put(None)


def _load(
    entry: str,
    *,
    adapter: str,
    factory: bool,
    loop: asyncio.AbstractEventLoop,
) -> Adapter:
    target = _import_entry(entry)
    if factory:
        target = target()
        if inspect.isawaitable(target):
            target = loop.run_until_complete(target)
    return load_adapter(target, adapter=adapter)


def _import_entry(entry: str) -> Any:
    module_name, separator, attribute = entry.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("entry must use module:attribute")
    value: Any = importlib.import_module(module_name)
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


def _description(adapter: Adapter) -> dict[str, Any]:
    described = adapter.describe()
    return {
        "type": "description",
        "protocol": PROTOCOL,
        "runtime": {
            "framework": described.get("framework"),
            "framework_version": described.get("framework_version"),
            "adapter": adapter.name,
            "harness_version": __version__,
            "python_version": platform.python_version(),
        },
        "tools": list(described.get("tools") or []),
        "limitations": list(described.get("limitations") or []),
    }


def _claim_stdout() -> IO[str]:
    """复制原 stdout 专用于协议，再把 fd 1 指向 stderr。"""

    sys.stdout.flush()
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(protocol_fd, "w", encoding="utf-8", buffering=1)


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agentrig.sdk.harness",
        description="Run a Python agent under AgentRig control.",
    )
    parser.add_argument(
        "--entry",
        required=True,
        help="module:attribute of an Agno Agent/Team, a compiled LangGraph graph, or a callable",
    )
    parser.add_argument("--adapter", choices=ADAPTER_NAMES, default="auto")
    parser.add_argument(
        "--factory",
        action="store_true",
        help="call the entry without arguments to build the agent first",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
