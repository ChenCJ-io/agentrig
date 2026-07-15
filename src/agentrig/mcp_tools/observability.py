"""observability 组：查看 proxy 录的工具调用 trace。"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..runtime import get_runtime


def list_traces_impl(tool_name: str | None = None) -> list[dict[str, Any]]:
    entries = get_runtime().trace.entries
    if tool_name:
        entries = [e for e in entries if e.tool_name == tool_name]
    return [
        {
            "tool": e.tool_name,
            "arguments": e.arguments,
            "source": e.source,
            "is_error": e.is_error,
        }
        for e in entries
    ]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_traces(tool_name: str | None = None) -> str:
        """proxy 录的工具调用 trace（可选按工具名过滤）。"""
        return json.dumps(list_traces_impl(tool_name), ensure_ascii=False, default=str)
