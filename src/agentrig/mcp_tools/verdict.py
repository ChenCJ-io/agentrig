"""verdict 组：取某用例最近一次 run 的判定。"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api import _runs


def get_verdict_impl(case_id: str) -> dict[str, Any] | str:
    for r in reversed(_runs):
        if r.get("scope") == case_id:
            return {
                "case_id": case_id,
                "run": r["id"],
                "passed": int(r.get("passed", 0)) == 1,
                "failed": int(r.get("failed", 0)),
            }
    return f"no run recorded for {case_id}"


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_verdict(case_id: str) -> str:
        """取某用例最近一次 run 的判定（passed/failed）。无记录返回提示。"""
        r = get_verdict_impl(case_id)
        return json.dumps(r, ensure_ascii=False, default=str) if isinstance(r, dict) else r
