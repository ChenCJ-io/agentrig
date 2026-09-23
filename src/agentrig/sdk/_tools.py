"""工具描述、参数绑定与结果还原，供 ``@tool`` 和各框架适配器共用。"""

from __future__ import annotations

import functools
import inspect
import json
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, overload

from ._runtime import active_runtime

F = TypeVar("F", bound=Callable[..., Any])

_PRIMITIVE_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}
_SCALAR_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "null"}


@dataclass(frozen=True)
class ToolSpec:
    """上报给 AgentRig Capability Snapshot 的工具定义。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    def to_capability(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
            or {"type": "object", "properties": {}},
            "output_schema": self.output_schema,
        }

    def result_schema(self) -> dict[str, Any]:
        """给 Provider 链的结果 Schema。

        结构化返回值保留 Schema，校验 Fixture 与 Curator 结果；标量返回值只保留说明，
        由适配器把 JSON 结果还原成原始类型，避免字符串工具的对象 Fixture 被判非法。
        Curator 能从 description 看到工具用途。
        """

        schema = dict(self.output_schema or {})
        if schema.get("type") in _SCALAR_SCHEMA_TYPES:
            schema = {}
        purpose = f"Result returned by tool `{self.name}`."
        if self.description.strip():
            purpose = f"{purpose} Tool description: {self.description.strip()}"
        existing = schema.get("description")
        schema["description"] = (
            f"{purpose} {existing}" if isinstance(existing, str) and existing else purpose
        )
        return schema


_REGISTRY: dict[str, ToolSpec] = {}


def registered_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


@overload
def tool(func: F, /) -> F: ...


@overload
def tool(*, name: str | None = None) -> Callable[[F], F]: ...


def tool(func: F | None = None, /, *, name: str | None = None) -> F | Callable[[F], F]:
    """标记一个不依赖框架的工具函数。

    不在 AgentRig harness 中时原样执行、没有额外开销。受控模式下不执行原函数，由 AgentRig
    按 Fixture → Sample → Simulation Curator 给出结果；观察模式下照常执行并上报结果。
    """

    def decorate(target: F) -> F:
        spec = describe_callable(target, name=name)
        _REGISTRY[spec.name] = spec
        signature = inspect.signature(target)
        returns = _type_hints(target).get("return", inspect.Signature.empty)
        result_schema = spec.result_schema()

        if inspect.iscoroutinefunction(target):

            @functools.wraps(target)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                runtime = active_runtime()
                if runtime is None:
                    return await target(*args, **kwargs)
                value = await runtime.aintercept(
                    spec.name,
                    bind_arguments(signature, args, kwargs),
                    lambda: target(*args, **kwargs),
                    result_schema=result_schema,
                )
                return restore_result(value, returns)

            return typing.cast(F, async_wrapper)

        @functools.wraps(target)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            runtime = active_runtime()
            if runtime is None:
                return target(*args, **kwargs)
            value = runtime.intercept(
                spec.name,
                bind_arguments(signature, args, kwargs),
                lambda: target(*args, **kwargs),
                result_schema=result_schema,
            )
            return restore_result(value, returns)

        return typing.cast(F, wrapper)

    if func is not None:
        return decorate(func)
    return decorate


def describe_callable(func: Callable[..., Any], *, name: str | None = None) -> ToolSpec:
    hints = _type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in inspect.signature(func).parameters.values():
        if parameter.name in {"self", "cls"} or parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        properties[parameter.name] = annotation_schema(
            hints.get(parameter.name, parameter.annotation)
        )
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    input_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        input_schema["required"] = required
    returns = hints.get("return", inspect.Signature.empty)
    output_schema = annotation_schema(returns) if returns is not type(None) else None
    return ToolSpec(
        name=name or func.__name__,
        description=inspect.getdoc(func) or "",
        input_schema=input_schema,
        output_schema=output_schema or None,
    )


def annotation_schema(annotation: Any) -> dict[str, Any]:
    """尽量把类型注解转成 JSON Schema；无法判断时返回不限制结构的空 Schema。"""

    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    primitive = _PRIMITIVE_TYPES.get(annotation)
    if primitive is not None:
        return {"type": primitive}
    try:
        from pydantic import TypeAdapter
    except ImportError:
        return {}
    try:
        schema = TypeAdapter(annotation).json_schema()
    except Exception:
        return {}
    return schema if isinstance(schema, dict) else {}


def bind_arguments(
    signature: inspect.Signature,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """按参数名还原调用参数，与模型发出的 tool call 参数形状一致。"""

    try:
        bound = signature.bind_partial(*args, **kwargs)
    except TypeError:
        return {"args": list(args), **kwargs}
    arguments: dict[str, Any] = {}
    for key, value in bound.arguments.items():
        if key in {"self", "cls"}:
            continue
        kind = signature.parameters[key].kind
        if kind is inspect.Parameter.VAR_KEYWORD:
            arguments.update(value)
        elif kind is inspect.Parameter.VAR_POSITIONAL:
            arguments[key] = list(value)
        else:
            arguments[key] = value
    return arguments


def restore_result(value: Any, annotation: Any) -> Any:
    """把 AgentRig 给出的 JSON 结果还原成工具声明的返回类型。"""

    if annotation is str:
        return value if isinstance(value, str) else as_text(value)
    model_validate = getattr(annotation, "model_validate", None)
    if isinstance(annotation, type) and callable(model_validate):
        if isinstance(value, annotation):
            return value
        try:
            return model_validate(value)
        except Exception:
            return value
    return value


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return typing.get_type_hints(func)
    except Exception:
        return {}
