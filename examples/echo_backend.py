"""Echo 后端 MCP server —— proxy 冒烟/测试用。

独立起::

    uvicorn examples.echo_backend:app --port 9001

endpoint 在根路径 `/`（streamable_http_path="/"）。让 proxy 连它::

    AGENTRIG_PROXY__BACKENDS='{"echo":"http://127.0.0.1:9001/"}' \\
    uvicorn agentrig.proxy.server:app --port 9000
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

# stateless_http + streamable_http_path="/" → endpoint 在 app 根路径
mcp = FastMCP("echo-backend", stateless_http=True, streamable_http_path="/")


@mcp.tool()
def echo(text: str) -> str:
    """原样返回输入（加 echo: 前缀）。"""
    return f"echo: {text}"


@mcp.tool()
def reverse(text: str) -> str:
    """反转文本。"""
    return text[::-1]


# FastMCP 的 streamable_http_app() 自带 lifespan（启动 session_manager）+ 路由
app = mcp.streamable_http_app()
