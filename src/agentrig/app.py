"""AgentRig V1 FastAPI 应用装配。

一个 ``agentrig serve`` 同时暴露 V1 HTTP API、原子 MCP Tools、CaseRun 级
MCP Proxy 和构建后的 Web SPA。

安全：可选 Bearer token（``server.api_token_ref`` 运行时解析；/api /mcp /proxy 需鉴权）+
安全响应头（CSP/nosniff/frame/referrer）。默认绑 127.0.0.1；公网暴露务必设 token。
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

from . import __version__
from .bootstrap import ServiceContainer
from .config import Settings, get_settings
from .errors import AgentRigError, ErrorCode, ErrorDetail
from .mcp_server import build_mcp_app, create_mcp_server, mcp_lifespan
from .proxy.aggregator import AgentRigProxy
from .proxy.backend import connect_backend
from .v1_api import router as v1_api_router


def create_app(services: ServiceContainer | None = None) -> FastAPI:
    settings = services.settings if services is not None else get_settings()
    service_container = services or ServiceContainer.build(settings)
    mcp_server = create_mcp_server(service_container)
    proxy = AgentRigProxy(
        service_container.backend_registry,
        scope_registry=service_container.proxy_scopes,
    )
    proxy_session_manager = StreamableHTTPSessionManager(app=proxy.build_server())
    proxy_endpoint = StreamableHTTPASGIApp(proxy_session_manager)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logging.getLogger("agentrig").info("AgentRig %s starting", __version__)
        await service_container.initialize()
        try:
            async with mcp_lifespan(mcp_server):
                async with AsyncExitStack() as stack:
                    for ns, url in settings.proxy.backends.items():
                        sess = await stack.enter_async_context(connect_backend(url))
                        service_container.backend_registry.add(ns, sess)
                    async with proxy_session_manager.run():
                        yield
        finally:
            await service_container.close()
        logging.getLogger("agentrig").info("AgentRig shutting down")

    app = FastAPI(title="AgentRig", version=__version__, lifespan=lifespan)
    app.state.services = service_container
    _add_security(app, settings)
    app.include_router(v1_api_router)
    _add_error_handlers(app)
    app.mount("/mcp", build_mcp_app(mcp_server))
    # proxy 用 Route 挂 StreamableHTTPASGIApp（参考 FastMCP.streamable_http_app 的挂法）：
    # Mount 会剥前缀使 ASGI 收到 / 而非 /proxy，POST 被 StreamableHTTPASGIApp 拒（405）。
    app.routes.append(Route("/proxy", endpoint=proxy_endpoint))
    _mount_spa(app)
    return app


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AgentRigError)
    async def _business_error(_request: Request, exc: AgentRigError) -> JSONResponse:
        status_code = {
            "not_found": 404,
            "permission_denied": 403,
            "conflict": 409,
        }.get(exc.detail.code.value, 400)
        return JSONResponse(
            exc.detail.model_dump(mode="json"),
            status_code=status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        detail = ErrorDetail(
            code=ErrorCode.VALIDATION_ERROR,
            message="request validation failed",
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(
            detail.model_dump(mode="json"),
            status_code=422,
        )


def _add_security(app: FastAPI, settings: Settings) -> None:
    logging.basicConfig(
        level=settings.server.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("agentrig")
    token = cast(ServiceContainer, app.state.services).server_api_token
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
            # RR8 SPA 模式依赖 inline script 注入路由上下文（window.__reactRouterContext），
            # 故 script-src 需 'unsafe-inline'；Google Fonts 经 CDN 引入。
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "img-src 'self' data:"
        )
        return resp


def _mount_spa(app: FastAPI, dist: Path | None = None) -> None:
    # 源码运行优先读仓库产物；wheel 安装后读取随包发布的同一份构建产物。
    if dist is None:
        source_dist = Path(__file__).resolve().parents[2] / "web" / "dist" / "client"
        packaged_dist = Path(__file__).resolve().parent / "web_dist"
        dist = source_dist if source_dist.is_dir() else packaged_dist
    if not dist.is_dir():
        return

    # SPA fallback 不是 HTTP API，不能进入 OpenAPI schema。闭包内的文件响应类型也不应
    # 被 Pydantic 当作业务响应模型分析。
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa(full_path: str) -> FileResponse:
        # 路径穿越防护：resolve 后必须仍在 dist 目录下（挡 %2e%2e / .. 等）
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
