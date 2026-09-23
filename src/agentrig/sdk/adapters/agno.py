"""Agno Agent/Team 适配：在 tool_hooks 链最内层接管用户声明的工具，用户代码无需改动。

- 只接管用户声明的工具；Team 委派、知识库检索等框架内置工具照常执行；
- Team 的 hook 只覆盖 Team 自己的工具，成员递归逐个安装；
- Agno 把工具返回值 ``str()`` 后交给模型，受控结果统一转成 JSON 文本，避免 dict 变成 repr；
- 2.x 的 ``cache_results`` 在 hook 之前命中缓存，还会把回放结果写回用户缓存，harness 内关闭。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .._runtime import CONTROLLED, HarnessContext, active_runtime, jsonable
from .._tools import ToolSpec, as_text
from .base import TurnOutput, package_version

# Team 的委派工具必须真实执行，否则成员永远不会运行。
_TEAM_BUILTINS = frozenset(
    {"delegate_task_to_member", "delegate_task_to_members", "get_member_information"}
)
_FAILED_STATUSES = {"error", "cancelled"}


class AgnoAdapter:
    name = "agno"

    def __init__(self, entity: Any) -> None:
        self._entity = entity
        self._specs: dict[str, ToolSpec] = {}
        self._limitations: set[str] = set()
        self._instrument(entity)
        if getattr(entity, "db", None) is None:
            # 没有 db 时 Agno 不保留会话历史；进程内存 db 只活在本次 CaseRun，不落盘。
            try:
                from agno.db.in_memory import InMemoryDb
            except ImportError:
                self._limitations.add("agno_in_memory_db_unavailable")
            else:
                entity.db = InMemoryDb()

    def describe(self) -> dict[str, Any]:
        return {
            "framework": "agno",
            "framework_version": package_version("agno"),
            "tools": [spec.to_capability() for spec in self._specs.values()],
            "limitations": sorted(self._limitations),
        }

    async def run_turn(self, message: str, context: HarnessContext) -> TurnOutput:
        options: dict[str, Any] = {"session_id": context.case_run_id or "agentrig", "stream": False}
        for key in ("user_id", "session_state", "dependencies"):
            value = context.initial_state.get(key)
            if value is not None:
                options[key] = value
        output = await self._entity.arun(message, **options)
        status = getattr(output, "status", None)
        status_text = str(getattr(status, "value", status) or "").lower()
        content = getattr(output, "content", None)
        if status_text in _FAILED_STATUSES:
            raise RuntimeError(f"agno run {status_text}: {content}")
        text = "" if content is None else as_text(jsonable(content))
        return TurnOutput(text=text, usage=_usage(output, self._entity))

    def _instrument(self, entity: Any) -> None:
        for spec in _declared_tools(entity):
            self._specs.setdefault(spec.name, spec)
        tools = getattr(entity, "tools", None)
        existing = list(getattr(entity, "tool_hooks", None) or [])
        if not existing and _has_per_tool_hooks(tools):
            # Agent 级 hooks 会整体替换 @tool(tool_hooks=...) 声明的单工具 hook。
            self._limitations.add("agno_per_tool_hooks_replaced")
        _disable_result_cache(tools)
        # 用户已有同步 hook 时保持同步链：异步 hook 会让链上的 next_func 变成协程，破坏用户 hook。
        asynchronous = all(inspect.iscoroutinefunction(hook) for hook in existing)
        entity.tool_hooks = [*existing, self._hook(entity, asynchronous=asynchronous)]
        members = getattr(entity, "members", None)
        if isinstance(members, list):
            for member in members:
                self._instrument(member)
        elif members is not None:
            self._limitations.add("agno_team_member_factory_not_instrumented")

    def _hook(self, entity: Any, *, asynchronous: bool) -> Callable[..., Any]:
        adapter = self

        if asynchronous:

            async def agentrig_tool_hook(
                function_name: str,
                function_call: Callable[..., Any],
                arguments: dict[str, Any],
            ) -> Any:
                runtime = active_runtime()
                if runtime is None or not _is_user_tool(entity, function_name):
                    return await _resolve(function_call(**arguments))
                value = await runtime.aintercept(
                    function_name,
                    dict(arguments),
                    lambda: _resolve(function_call(**arguments)),
                    result_schema=adapter._result_schema(function_name),
                )
                return as_text(value) if runtime.context.tool_mode == CONTROLLED else value

            return agentrig_tool_hook

        def agentrig_sync_tool_hook(
            function_name: str,
            function_call: Callable[..., Any],
            arguments: dict[str, Any],
        ) -> Any:
            runtime = active_runtime()
            if runtime is None or not _is_user_tool(entity, function_name):
                return function_call(**arguments)
            value = runtime.intercept(
                function_name,
                dict(arguments),
                lambda: function_call(**arguments),
                result_schema=adapter._result_schema(function_name),
            )
            return as_text(value) if runtime.context.tool_mode == CONTROLLED else value

        return agentrig_sync_tool_hook

    def _result_schema(self, name: str) -> dict[str, Any]:
        return self._specs.get(name, ToolSpec(name=name)).result_schema()


async def _resolve(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _is_user_tool(entity: Any, name: str) -> bool:
    """按调用时的工具集判断，MCPTools 连接后才出现的工具也能识别。"""

    tools = getattr(entity, "tools", None)
    if not isinstance(tools, list):
        return name not in _TEAM_BUILTINS
    for item in tools:
        functions = getattr(item, "functions", None)
        if isinstance(functions, dict):
            if name in functions or name in (getattr(item, "async_functions", None) or {}):
                return True
        elif getattr(item, "name", None) == name or getattr(item, "__name__", None) == name:
            return True
    return False


def _declared_tools(entity: Any) -> list[ToolSpec]:
    """与 Agno parse_tools 相同的方式静态生成工具定义；MCP 工具连接前无法列出。"""

    tools = getattr(entity, "tools", None)
    if not isinstance(tools, list):
        return []
    try:
        from agno.tools.function import Function
        from agno.tools.toolkit import Toolkit
    except ImportError:
        return []
    specs: list[ToolSpec] = []
    for item in tools:
        try:
            if isinstance(item, Toolkit):
                source = (
                    item.get_async_functions()
                    if hasattr(item, "get_async_functions")
                    else item.get_functions()
                )
                functions = []
                for function in source.values():
                    copied = function.model_copy()
                    copied.process_entrypoint(strict=False)
                    functions.append(copied)
            elif isinstance(item, Function):
                copied = item.model_copy()
                copied.process_entrypoint(strict=False)
                functions = [copied]
            elif callable(item):
                functions = [Function.from_callable(item, strict=False)]
            else:
                continue
        except Exception:
            continue
        for function in functions:
            definition = function.to_dict()
            parameters = definition.get("parameters")
            specs.append(
                ToolSpec(
                    name=str(definition["name"]),
                    description=str(definition.get("description") or ""),
                    input_schema=parameters if isinstance(parameters, dict) else None,
                )
            )
    return specs


def _has_per_tool_hooks(tools: Any) -> bool:
    if not isinstance(tools, list):
        return False
    return any(getattr(item, "tool_hooks", None) for item in tools)


def _disable_result_cache(tools: Any) -> None:
    if not isinstance(tools, list):
        return
    for item in tools:
        functions = getattr(item, "functions", None)
        targets = [item, *(functions.values() if isinstance(functions, dict) else [])]
        for target in targets:
            if getattr(target, "cache_results", False):
                target.cache_results = False


def _usage(output: Any, entity: Any) -> list[dict[str, Any]]:
    metrics = getattr(output, "metrics", None)
    if metrics is None:
        return []
    usage: dict[str, Any] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = getattr(metrics, key, None)
        if isinstance(value, int):
            usage[key] = value
    if not any(usage.values()):
        return []
    cached = getattr(metrics, "cache_read_tokens", None)
    if isinstance(cached, int) and cached:
        usage["cached_input_tokens"] = cached
    model = getattr(getattr(entity, "model", None), "id", None)
    if isinstance(model, str) and model:
        usage["model"] = model
    return [usage]
