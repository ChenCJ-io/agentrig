"""sampling 组 MCP 工具：从 proxy 录的 trace 取真实工具返回样本。

CC 写用例前调 get_real_tool_samples，拿真实工具返回结构作参考，
避免凭空臆造 mock（贴合真实 agent 行为）。
"""
from __future__ import annotations

import json
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP

from ..proxy.trace import TraceEntry
from ..runtime import get_runtime


def _entry_to_sample(e: TraceEntry) -> dict[str, Any]:
    """把 trace entry 转成可序列化样本。

    result：real 是 ContentBlock 列表（提取 text），mock 是原始值（原样）。
    """
    result = e.result
    if isinstance(result, list) and result and isinstance(result[0], types.TextContent):
        result_out: Any = [b.text for b in result if isinstance(b, types.TextContent)]
    elif isinstance(result, list):
        result_out = [str(b) for b in result]
    else:
        result_out = result
    return {
        "tool_name": e.tool_name,
        "arguments": e.arguments,
        "source": e.source,
        "is_error": e.is_error,
        "result": result_out,
    }


def get_real_tool_samples_impl(
    tool_name: str | None = None,
    *,
    source: str | None = "real",
) -> list[dict[str, Any]]:
    """从 runtime trace 读样本，按 tool_name / source 过滤。

    默认只取 real（真实工具返回）；source=None 取全部（含 mock）。
    """
    out: list[dict[str, Any]] = []
    for e in get_runtime().trace.entries:
        if tool_name is not None and e.tool_name != tool_name:
            continue
        if source is not None and e.source != source:
            continue
        out.append(_entry_to_sample(e))
    return out


def register(mcp: FastMCP) -> None:
    """注册 sampling 工具到 FastMCP。"""

    @mcp.tool()
    def get_real_tool_samples(tool_name: str | None = None) -> str:
        """取真实工具返回样本（从 proxy trace 录制）。

        CC 写用例前调用，拿真实工具返回结构作参考。可选 tool_name 过滤。
        """
        samples = get_real_tool_samples_impl(tool_name, source="real")
        return json.dumps(samples, ensure_ascii=False, default=str)
