"""FastAPI 应用装配。

lifespan 启动 MCP session manager（/mcp 工具）+ proxy session manager（/proxy 代理，
连后端）。一个 `agentrig serve` 同时暴露：
- /mcp：ping + authoring + execution 工具（CC 操作 AgentRig 的入口）
- /proxy：MCP proxy（agent 连这里用工具，AgentRig 聚合 + mock + trace）

无 proxy.backends 配置时，/proxy 仍起（空后端，list_tools 返回空）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import cast

from fastapi import FastAPI
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import ASGIApp

from . import __version__
from .config import get_settings
from .mcp_server import build_mcp_app, mcp_lifespan
from .proxy.aggregator import AgentRigProxy
from .proxy.backend import BackendRegistry, connect_backend


def create_app() -> FastAPI:
    settings = get_settings()

    # proxy 组件（lifespan 和挂载共用同一实例）
    proxy_registry = BackendRegistry()
    proxy = AgentRigProxy(proxy_registry)
    proxy_session_manager = StreamableHTTPSessionManager(app=proxy.build_server())
    proxy_endpoint = StreamableHTTPASGIApp(proxy_session_manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        print(f"AgentRig {__version__} starting")
        async with mcp_lifespan():
            async with AsyncExitStack() as stack:
                # 连所有配置的后端（长连，退出时 stack 自动断）
                for ns, url in settings.proxy.backends.items():
                    sess = await stack.enter_async_context(connect_backend(url))
                    proxy_registry.add(ns, sess)
                async with proxy_session_manager.run():
                    yield
        print("AgentRig shutting down")

    app = FastAPI(title="AgentRig", version=__version__, lifespan=lifespan)
    app.mount("/mcp", build_mcp_app())
    app.mount("/proxy", cast(ASGIApp, proxy_endpoint))
    return app


app = create_app()
