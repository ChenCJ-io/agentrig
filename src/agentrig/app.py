"""FastAPI 应用装配。

lifespan 把 MCP server 挂载到 `/mcp` 并启动其 session manager task group。
后续 PR 在此装配 AppState（仓储、transport 等）；v0.1-alpha 不接 DB。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .mcp_server import build_mcp_app, mcp_lifespan


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    print(f"AgentRig {__version__} starting")
    async with mcp_lifespan():
        yield
    print("AgentRig shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="AgentRig", version=__version__, lifespan=lifespan)
    app.mount("/mcp", build_mcp_app())
    return app


app = create_app()
