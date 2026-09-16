"""MCP 结果投影与结构化业务错误。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Sequence
from typing import Any, TypeVar

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import BaseModel

from ...errors import AgentRigError

T = TypeVar("T")


async def invoke(value: Awaitable[T]) -> T:
    try:
        return await value
    except AgentRigError as exc:
        raise ToolError(
            json.dumps(exc.detail.model_dump(mode="json"), ensure_ascii=False)
        ) from exc


def dump_model(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def dump_models(value: Sequence[BaseModel]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in value]
