"""AgentRig MCP server（FastMCP）。

通过 streamable HTTP 暴露在 `/mcp`。`stateless_http=True` 配合
`streamable_http_path="/"` 和 `app.mount("/mcp")`，得到干净的 `/mcp/`
端点（否则路径会变成 `/mcp/mcp`）。

session manager 的 task group 必须在 app lifespan 里启动 —— 见下方的
`mcp_lifespan`，在 `app.py` 里嵌套使用。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp

from .mcp_tools import authoring, execution, sampling

mcp: FastMCP = FastMCP("agentrig", stateless_http=True, streamable_http_path="/")


@mcp.tool()
def ping() -> str:
    """健康检查 —— 返回 'pong'。"""
    return "pong"


# 注册工具组（authoring: 构建/查询；execution: 跑用例；sampling: 真实样本；后续 results/verdict/...）
authoring.register(mcp)
execution.register(mcp)
sampling.register(mcp)


def build_mcp_app() -> ASGIApp:
    """返回 streamable-HTTP ASGI app，供 FastAPI 挂载到 /mcp。"""
    return cast(ASGIApp, mcp.streamable_http_app())


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    """启动 FastMCP session manager 的 task group（streamable HTTP 必需）。

    必须嵌套在 FastAPI app lifespan 内使用。
    """
    async with mcp.session_manager.run():
        yield
