"""FastAPI 应用装配。

lifespan：MCP session manager（/mcp）+ proxy（/proxy）。一个 `agentrig serve` 同时暴露：
- /api：REST API（前端 web 用）
- /mcp：authoring/execution/sampling/discovery/results/verdict/observability 工具
- /proxy：MCP proxy（agent 连这里用工具，AgentRig 聚合 + mock + trace）

安全：可选 Bearer token（AGENTRIG_SERVER__API_TOKEN 非空时 /api /mcp /proxy 需鉴权）+
安全响应头（CSP/nosniff/frame/referrer）。默认绑 127.0.0.1；公网暴露务必设 token。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.types import ASGIApp

from . import __version__
from .api import router as api_router
from .config import Settings, get_settings
from .mcp_server import build_mcp_app, mcp_lifespan
from .proxy.aggregator import AgentRigProxy
from .proxy.backend import connect_backend
from .runtime import get_runtime
from .seed import maybe_seed


def create_app() -> FastAPI:
    settings = get_settings()
    maybe_seed()

    rt = get_runtime()
    proxy = AgentRigProxy(rt.registry, mock_policy=rt.hub, trace_sink=rt.trace)
    proxy_session_manager = StreamableHTTPSessionManager(app=proxy.build_server())
    proxy_endpoint = StreamableHTTPASGIApp(proxy_session_manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logging.getLogger("agentrig").info("AgentRig %s starting", __version__)
        async with mcp_lifespan():
            async with AsyncExitStack() as stack:
                for ns, url in settings.proxy.backends.items():
                    sess = await stack.enter_async_context(connect_backend(url))
                    rt.registry.add(ns, sess)
                async with proxy_session_manager.run():
                    yield
        logging.getLogger("agentrig").info("AgentRig shutting down")

    app = FastAPI(title="AgentRig", version=__version__, lifespan=lifespan)
    _add_security(app, settings)
    app.include_router(api_router)
    app.mount("/mcp", build_mcp_app())
    app.mount("/proxy", cast(ASGIApp, proxy_endpoint))
    _mount_spa(app)
    return app


def _add_security(app: FastAPI, settings: Settings) -> None:
    logging.basicConfig(
        level=settings.server.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("agentrig")
    token = settings.server.api_token
    protected = ("/api", "/mcp", "/proxy")
    if token:
        logger.warning("API token 鉴权已启用：/api /mcp /proxy 需 Authorization: Bearer <token>")

    @app.middleware("http")
    async def _token_guard(request: Request, call_next: Any) -> Response:
        if token and any(request.url.path.startswith(p) for p in protected):
            if request.headers.get("authorization", "") != f"Bearer {token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return cast(Response, await call_next(request))

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Response:
        resp = cast(Response, await call_next(request))
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:"
        )
        return resp


def _mount_spa(app: FastAPI) -> None:
    from pathlib import Path

    from starlette.responses import FileResponse

    dist = Path("web/dist").resolve()
    if not dist.is_dir():
        return

    @app.get("/{full_path:path}")
    async def _spa(full_path: str) -> FileResponse:
        # 路径穿越防护：resolve 后必须仍在 dist 目录下（挡 %2e%2e / .. 等）
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
