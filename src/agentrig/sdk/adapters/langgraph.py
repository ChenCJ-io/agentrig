"""LangGraph 编译图适配：在 ToolNode 上接管工具执行，用户代码无需改动。

``create_agent``、``create_react_agent`` 和手写 StateGraph 都用 ToolNode 执行工具。拦截器
装在 ToolNode 的 wrap_tool_call 链最内层，用户自己的 middleware 照常运行，只替换真实工具
函数；旧版 langgraph-prebuilt（≤ 1.0.1）没有该链，退回替换 ``_run_one``。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .._runtime import HarnessContext, active_runtime
from .._tools import ToolSpec, as_text
from .base import TurnOutput, package_version


class LangGraphAdapter:
    name = "langgraph"

    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self._tools: dict[str, Any] = {}
        self._limitations: set[str] = set()
        self._messages: list[Any] = []
        nodes = _find_tool_nodes(graph, set())
        if not nodes:
            self._limitations.add("langgraph_tool_node_not_found")
        for node in nodes:
            tools = getattr(node, "tools_by_name", None)
            if isinstance(tools, dict):
                self._tools.update(tools)
            if not self._install(node):
                self._limitations.add("langgraph_tool_node_not_interceptable")
        self._specs = {name: _describe_tool(name, tool) for name, tool in self._tools.items()}
        self._checkpointed = _has_checkpointer(graph)

    def describe(self) -> dict[str, Any]:
        return {
            "framework": "langgraph",
            "framework_version": package_version("langgraph"),
            "tools": [self._specs[name].to_capability() for name in sorted(self._specs)],
            "limitations": sorted(self._limitations),
        }

    async def run_turn(self, message: str, context: HarnessContext) -> TurnOutput:
        from langchain_core.messages import AIMessage, HumanMessage

        marker = f"agentrig-{context.case_run_id or 'local'}-{context.turn}"
        human = HumanMessage(content=message, id=marker)
        config: dict[str, Any] | None = None
        if self._checkpointed:
            payload = {"messages": [human]}
            config = {"configurable": {"thread_id": context.case_run_id or "agentrig"}}
        else:
            payload = {"messages": [*self._messages, human]}
        state = await self._graph.ainvoke(payload, config=config)
        messages = list(state.get("messages") or []) if isinstance(state, dict) else []
        self._messages = messages
        start = next(
            (index + 1 for index, item in enumerate(messages) if getattr(item, "id", None) == marker),
            0,
        )
        replies = [item for item in messages[start:] if isinstance(item, AIMessage)]
        text = _message_text(replies[-1]) if replies else ""
        usage = [item for item in (_usage(reply) for reply in replies) if item]
        return TurnOutput(text=text, usage=usage)

    def _install(self, node: Any) -> bool:
        adapter = self
        if hasattr(node, "_wrap_tool_call") and hasattr(node, "_awrap_tool_call"):
            original = node._wrap_tool_call
            original_async = node._awrap_tool_call

            def wrap(request: Any, execute: Callable[[Any], Any]) -> Any:
                def innermost(inner: Any) -> Any:
                    return adapter._call(inner, execute)

                return original(request, innermost) if original else innermost(request)

            async def awrap(request: Any, execute: Callable[[Any], Awaitable[Any]]) -> Any:
                async def innermost(inner: Any) -> Any:
                    return await adapter._acall(inner, execute)

                if original_async is not None:
                    return await original_async(request, innermost)
                return await innermost(request)

            node._wrap_tool_call = wrap
            # 用户只有同步 middleware 时保持为空，ToolNode 在异步路径会回落到同步链，与原行为一致。
            node._awrap_tool_call = (
                awrap if original_async is not None or original is None else None
            )
            return True
        if hasattr(node, "_run_one") and hasattr(node, "_arun_one"):
            run_one = node._run_one
            arun_one = node._arun_one

            def patched_run_one(call: Any, input_type: Any, config: Any) -> Any:
                return adapter._intercept(call, lambda: run_one(call, input_type, config))

            async def patched_arun_one(call: Any, input_type: Any, config: Any) -> Any:
                return await adapter._aintercept(
                    call,
                    lambda: arun_one(call, input_type, config),
                )

            node._run_one = patched_run_one
            node._arun_one = patched_arun_one
            return True
        return False

    def _call(self, request: Any, execute: Callable[[Any], Any]) -> Any:
        if getattr(request, "tool", None) is None:
            # 模型调用了不存在的工具：交给 ToolNode 返回标准错误，不进入 Provider 链。
            return execute(request)
        return self._intercept(request.tool_call, lambda: execute(request))

    async def _acall(self, request: Any, execute: Callable[[Any], Awaitable[Any]]) -> Any:
        if getattr(request, "tool", None) is None:
            return await execute(request)
        return await self._aintercept(request.tool_call, lambda: execute(request))

    def _intercept(self, call: dict[str, Any], execute: Callable[[], Any]) -> Any:
        runtime = active_runtime()
        if runtime is None:
            return execute()
        name = str(call.get("name") or "")
        value = runtime.intercept(
            name,
            dict(call.get("args") or {}),
            execute,
            call_id=_optional_id(call),
            result_schema=self._spec(name).result_schema(),
        )
        return _tool_message(value, call)

    async def _aintercept(
        self,
        call: dict[str, Any],
        execute: Callable[[], Awaitable[Any]],
    ) -> Any:
        runtime = active_runtime()
        if runtime is None:
            return await execute()
        name = str(call.get("name") or "")
        value = await runtime.aintercept(
            name,
            dict(call.get("args") or {}),
            execute,
            call_id=_optional_id(call),
            result_schema=self._spec(name).result_schema(),
        )
        return _tool_message(value, call)

    def _spec(self, name: str) -> ToolSpec:
        return self._specs.get(name) or ToolSpec(name=name)


def _describe_tool(name: str, tool: Any) -> ToolSpec:
    """用 LangChain 发给模型的同一份定义描述工具；注入参数不会出现在 Schema 里。"""

    definition: dict[str, Any] = {}
    try:
        from langchain_core.utils.function_calling import convert_to_openai_tool

        definition = dict(convert_to_openai_tool(tool).get("function") or {})
    except Exception:
        definition = {}
    parameters = definition.get("parameters")
    return ToolSpec(
        name=name,
        description=str(definition.get("description") or getattr(tool, "description", "") or ""),
        input_schema=parameters if isinstance(parameters, dict) else None,
    )


def _tool_message(value: Any, call: dict[str, Any]) -> Any:
    """受控结果包装成 ToolMessage；观察模式下 ToolNode 返回的消息或 Command 原样透传。"""

    from langchain_core.messages import ToolMessage

    if isinstance(value, ToolMessage) or _has_class(value, "langgraph", {"Command"}):
        return value
    try:
        from langgraph.prebuilt.tool_node import msg_content_output

        content: Any = msg_content_output(value)
    except ImportError:
        content = as_text(value)
    return ToolMessage(
        content=content,
        tool_call_id=str(call.get("id") or ""),
        name=str(call.get("name") or ""),
    )


def _find_tool_nodes(graph: Any, seen: set[int]) -> list[Any]:
    if id(graph) in seen:
        return []
    seen.add(id(graph))
    nodes = getattr(graph, "nodes", None)
    if not isinstance(nodes, dict):
        return []
    found: list[Any] = []
    for node in nodes.values():
        bound = getattr(node, "bound", None)
        if _has_class(bound, "langgraph", {"ToolNode"}) or _has_class(
            bound, "langchain", {"ToolNode", "_ToolNode"}
        ):
            found.append(bound)
        elif _has_class(bound, "langgraph", {"Pregel"}):
            found.extend(_find_tool_nodes(bound, seen))
    return found


def _has_class(value: Any, root: str, names: set[str]) -> bool:
    return any(
        cls.__name__ in names and cls.__module__.split(".", 1)[0] == root
        for cls in type(value).__mro__
    )


def _has_checkpointer(graph: Any) -> bool:
    try:
        from langgraph.checkpoint.base import BaseCheckpointSaver
    except ImportError:
        return False
    return isinstance(getattr(graph, "checkpointer", None), BaseCheckpointSaver)


def _optional_id(call: dict[str, Any]) -> str | None:
    identifier = call.get("id")
    return str(identifier) if identifier else None


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return as_text(content)


def _usage(message: Any) -> dict[str, Any] | None:
    metadata = getattr(message, "usage_metadata", None)
    if not isinstance(metadata, dict) or not metadata:
        return None
    usage: dict[str, Any] = {
        key: metadata[key]
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance(metadata.get(key), int)
    }
    details = metadata.get("input_token_details")
    if isinstance(details, dict) and isinstance(details.get("cache_read"), int):
        usage["cached_input_tokens"] = details["cache_read"]
    response = getattr(message, "response_metadata", None)
    if isinstance(response, dict):
        model = response.get("model_name") or response.get("model")
        if isinstance(model, str) and model:
            usage["model"] = model
    return usage
