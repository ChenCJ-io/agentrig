"""discovery 组：让 CC 发现 AgentRig 能力（工具清单 + 用例 schema）。

CC 调 list_agentrig_tools 知道有哪些工具，调 get_case_schema 拿用例字段（不硬编码）。
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..models import TestCase

_AGENTRIG_TOOLS: list[dict[str, str]] = [
    {"name": "upsert_test_case", "group": "authoring", "desc": "创建/更新用例"},
    {"name": "list_test_cases", "group": "authoring", "desc": "列出用例"},
    {"name": "get_test_case", "group": "authoring", "desc": "取单个用例"},
    {"name": "run_single_case", "group": "execution", "desc": "跑用例并机判"},
    {"name": "get_real_tool_samples", "group": "sampling", "desc": "取真实工具返回样本"},
    {"name": "list_agentrig_tools", "group": "discovery", "desc": "列 AgentRig 全部工具"},
    {"name": "get_case_schema", "group": "discovery", "desc": "用例字段 schema"},
    {"name": "list_runs", "group": "results", "desc": "近期 run 历史"},
    {"name": "get_verdict", "group": "verdict", "desc": "用例最近判定"},
    {"name": "list_traces", "group": "observability", "desc": "proxy trace"},
]


def list_agentrig_tools_impl() -> list[dict[str, str]]:
    return _AGENTRIG_TOOLS


def get_case_schema_impl() -> dict[str, Any]:
    """TestCase 各字段 → 类型注解字符串（CC 写用例参考）。"""
    return {name: str(fi.annotation) for name, fi in TestCase.model_fields.items()}


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def list_agentrig_tools() -> str:
        """列出 AgentRig 提供的全部 MCP 工具（name/group/说明）。"""
        return json.dumps(list_agentrig_tools_impl(), ensure_ascii=False)

    @mcp.tool()
    def get_case_schema() -> str:
        """TestCase 字段 schema（写用例时参考，不要硬编码字段）。"""
        return json.dumps(get_case_schema_impl(), ensure_ascii=False)
