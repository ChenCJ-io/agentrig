"""AgentRig V1/V2 FastAPI 应用装配。

一个 ``agentrig serve`` 同时暴露 V1/V2 HTTP API、控制方与角色 MCP Tools、
CaseRun 级 MCP Proxy 和构建后的 Web SPA。

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
from .mcp_server import (
    build_mcp_app,
    create_mcp_server,
    create_role_mcp_servers,
    mcp_lifespan,
)
from .production.api import router as otlp_router
from .projects.schemas import ProjectScope
from .proxy.aggregator import AgentRigProxy
from .proxy.backend import connect_backend
from .v1_api import router as v1_api_router
from .v2_api import router as v2_api_router

_AGENTTEAMS_MCP_PATHS = {
    role: f"/mcp-servers/mcp-agentrig-{role}/mcp"
    for role in ("manager", "curator", "judge")
}


class _RootPathASGI:
    """把精确 Route 别名改写为 FastMCP streamable HTTP 的根路径。"""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        rewritten = dict(scope)
        rewritten["path"] = "/"
        rewritten["raw_path"] = b"/"
        await self._app(rewritten, receive, send)


def create_app(services: ServiceContainer | None = None) -> FastAPI:
    settings = services.settings if services is not None else get_settings()
    service_container = services or ServiceContainer.build(settings)
    mcp_server = create_mcp_server(service_container)
    role_mcp_servers = create_role_mcp_servers(service_container)
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
                    for role_server in role_mcp_servers.values():
                        await stack.enter_async_context(mcp_lifespan(role_server))
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
    app.include_router(v2_api_router)
    app.include_router(otlp_router)
    _add_error_handlers(app)
    for role, role_server in role_mcp_servers.items():
        role_app = build_mcp_app(role_server)
        app.mount(f"/mcp/{role}", role_app)
        # AgentTeams v1.1.2 的 Higress mcp-proxy 在本地 DNS upstream 下会保留
        # `/mcp-servers/<name>/mcp` 原路径。用同一个角色 ASGI app 提供精确别名，
        # 仍由下方 middleware 校验该角色的独立 upstream token。
        app.routes.append(
            Route(_AGENTTEAMS_MCP_PATHS[role], endpoint=_RootPathASGI(role_app))
        )
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
            "assistant_turn_conflict": 409,
            "plan_stale": 409,
            "plan_already_submitted": 409,
            "plan_confirmation_required": 409,
            "decision_invalid": 422,
            "decision_denied": 403,
            "decision_confirmation_required": 409,
            "decision_stale": 409,
            "decision_action_mismatch": 409,
            "decision_already_claimed": 409,
            "decision_retry_exhausted": 409,
            "decision_required": 409,
            "agent_role_forbidden": 403,
            "agentteams_unavailable": 503,
            "assistant_provider_unavailable": 503,
            "matrix_delivery_failed": 503,
            "agent_invocation_timed_out": 504,
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
    role_tokens = cast(ServiceContainer, app.state.services).role_mcp_tokens
    protected = ("/api", "/mcp", "/proxy")
    if token:
        logger.warning("API token 鉴权已启用：/api /mcp /proxy 需 Authorization: Bearer <token>")

    @app.middleware("http")
    async def _token_guard(request: Request, call_next: Any) -> Response:
        role = next(
            (
                item
                for item in ("manager", "curator", "judge")
                if request.url.path.startswith(f"/mcp/{item}")
                or request.url.path == _AGENTTEAMS_MCP_PATHS[item]
            ),
            None,
        )
        if role is not None:
            expected = role_tokens.get(role)
            if expected is None or request.headers.get("authorization", "") != (
                f"Bearer {expected}"
            ):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        elif request.url.path == "/v1/traces":
            # The OTLP receiver authenticates an ingest-source token and must not
            # accept the deployment-wide API token as an ingest credential.
            pass
        elif token and any(request.url.path.startswith(p) for p in protected):
            authorization = request.headers.get("authorization", "")
            project_parts = request.url.path.split("/")
            project_id = (
                project_parts[3]
                if len(project_parts) > 3
                and project_parts[1:3] == ["api", "projects"]
                else None
            )
            project_token = authorization.removeprefix("Bearer ")
            if project_id and project_token.startswith("agrp_"):
                required_scope = _required_project_scope(
                    request.method,
                    request.url.path,
                )
                try:
                    request.state.project_context = await cast(
                        ServiceContainer,
                        app.state.services,
                    ).projects.authenticate(project_id, project_token, required_scope)
                except AgentRigError:
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
            elif authorization != f"Bearer {token}":
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


def _required_project_scope(method: str, path: str) -> ProjectScope:
    """Map project routes to the least privilege needed for this operation."""

    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if "/execution-jobs" in path:
        return "run"
    if "/production/ingest-sources" in path:
        return "ingest"
    if "/production/traces/" in path and "/case-drafts" in path:
        return "review"
    if "/evaluators/versions" in path:
        return "admin" if path.endswith(":activate") else "review"
    if any(item in path for item in ("/review-items", "/failure-")):
        return "review"
    if any(item in path for item in ("/api-keys", "/environments")):
        return "admin"
    return "admin"


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
