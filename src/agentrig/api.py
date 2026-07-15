"""REST API（/api）：供前端 web 调用。

复用 storage / execution / sampling 的纯函数，不重复逻辑。run 记录进 in-memory
历史（alpha；后续接持久化），overview 据此算 metrics。
"""
from __future__ import annotations

from collections import deque
from typing import Any

from fastapi import APIRouter, HTTPException

from .mcp_tools.execution import run_single_case_impl
from .mcp_tools.sampling import get_real_tool_samples_impl
from .models import TestCase
from .storage import get_repo

router = APIRouter(prefix="/api", tags=["agentrig"])

# 简单 in-memory run 历史（alpha；后续 PR 接持久化）。deque 有界，防无限增长。
_runs: deque[dict[str, Any]] = deque(maxlen=500)


@router.get("/overview")
async def overview() -> dict[str, Any]:
    cases = get_repo().list_all()
    total = len(cases)
    passed = sum(1 for r in _runs if r["passed"])
    failed = sum(1 for r in _runs if not r["passed"])
    pass_rate = round(passed / len(_runs) * 100, 1) if _runs else 0.0
    return {
        "total_cases": total,
        "pass_rate": pass_rate,
        "median_run": "—",
        "changed_tools": 0,
        "passed": passed,
        "failed": failed,
        "skipped": 0,
        "coverage_done": passed,
        "coverage_total": total or 1,
        "recent_runs": list(reversed(_runs))[:6],
        "suite_growth": [{"name": c.id, "delta": 1, "when": ""} for c in cases[:5]],
    }


@router.get("/cases")
async def list_cases() -> list[dict[str, Any]]:
    return [c.model_dump() for c in get_repo().list_all()]


@router.get("/cases/{case_id}")
async def get_case(case_id: str) -> dict[str, Any]:
    c = get_repo().get(case_id)
    if c is None:
        raise HTTPException(status_code=404, detail=f"not found: {case_id}")
    return c.model_dump()


@router.put("/cases/{case_id}")
async def upsert_case(case_id: str, case: dict[str, Any]) -> dict[str, Any]:
    # path id 与 body id 对齐（以 path 为准）
    payload = {**case, "id": case_id}
    tc = TestCase(**payload)
    get_repo().upsert(tc)
    return tc.model_dump()


@router.post("/cases/{case_id}/run")
async def run_case(case_id: str) -> dict[str, Any]:
    result = await run_single_case_impl(get_repo(), case_id)
    if "passed" in result:
        _runs.append(
            {
                "id": f"AR-{100 + len(_runs) + 1}",
                "commit": "local",
                "scope": case_id,
                "passed": 1 if result["passed"] else 0,
                "failed": 0 if result["passed"] else 1,
                "total": 1,
                "duration": "—",
                "when": "just now",
            }
        )
    return result


@router.get("/tool-samples")
async def tool_samples(tool_name: str | None = None) -> list[dict[str, Any]]:
    return get_real_tool_samples_impl(tool_name, source="real")
