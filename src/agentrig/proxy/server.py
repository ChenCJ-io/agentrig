"""Proxy ASGI 挂载：把 AgentRigProxy 暴露为可独立起的 ASGI app。

启动时连所有配置的后端（长连），session_manager.run() 在 lifespan 启动。
独立起::

    AGENTRIG_PROXY__BACKENDS='{"echo":"http://localhost:9001/mcp"}' \\
    uvicorn agentrig.proxy.server:app --port 9000
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Route

from ..config import get_settings
from ..runtime import get_runtime
from .aggregator import AgentRigProxy
from .backend import BackendRegistry, connect_backend
from .mock_policy import MockPolicy
from .trace import TraceSink


def build_proxy_app(
    backends_config: dict[str, str],
    *,
    mock_policy: MockPolicy | None = None,
    trace_sink: TraceSink | None = None,
) -> Starlette:
    """构建 proxy ASGI app。

    backends_config: {namespace: backend_url}，启动时连所有后端。
    """
    registry = BackendRegistry()
    proxy = AgentRigProxy(registry, mock_policy=mock_policy, trace_sink=trace_sink)
    session_manager = StreamableHTTPSessionManager(app=proxy.build_server())
    asgi_endpoint = StreamableHTTPASGIApp(session_manager)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        # 连所有后端（长连），整段 session_manager.run() 期间持有
        async with AsyncExitStack() as stack:
            for ns, url in backends_config.items():
                sess = await stack.enter_async_context(connect_backend(url))
                registry.add(ns, sess)
            async with session_manager.run():
                yield

    return Starlette(routes=[Route("/mcp", endpoint=asgi_endpoint)], lifespan=lifespan)


# 模块级默认 app（从环境变量读 backends，注入 runtime 的 mock hub + trace），
# 供 `uvicorn agentrig.proxy.server:app`
_settings = get_settings()
_rt = get_runtime()
app = build_proxy_app(
    dict(_settings.proxy.backends),
    mock_policy=_rt.hub,
    trace_sink=_rt.trace,
)
