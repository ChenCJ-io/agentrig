"""results 组：查看 run 历史（来自 /api 的 in-memory 记录）。"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import _runs  # in-memory run 历史（与 /api 共享同一 list 对象）


def list_runs_impl(limit: int = 20) -> list[dict[str, Any]]:
    return list(reversed(_runs))[:limit]


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_runs(limit: int = 20) -> str:
        """近期 run 历史（默认最近 20 条，按时间倒序）。"""
        return json.dumps(list_runs_impl(limit), ensure_ascii=False, default=str)
