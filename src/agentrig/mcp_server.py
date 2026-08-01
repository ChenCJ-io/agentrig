"""AgentRig MCP server（FastMCP）。

通过 streamable HTTP 暴露在 `/mcp`。`stateless_http=True` 配合
`streamable_http_path="/"` 和 `app.mount("/mcp")`，得到干净的 `/mcp/`
端点（否则路径会变成 `/mcp/mcp`）。

session manager 的 task group 必须在 app lifespan 里启动 —— 见下方的
`mcp_lifespan`，在 `app.py` 里嵌套使用。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock
from pydantic import BaseModel
from starlette.types import ASGIApp

from .bootstrap import ServiceContainer
from .mcp.tools import register_all as register_v1_tools
from .mcp.v2 import register_curator, register_judge, register_manager_tools

_RESOURCE_ID = re.compile(
    r"\b(?:asstevt|asstturn|asst|agentinv|plan|case_run|run|case|target|profile|sample|evaluation)_[A-Za-z0-9_.:-]+\b"
)
_LOGGER = logging.getLogger("agentrig.mcp.audit")


class AuditedFastMCP(FastMCP):
    """在协议调用边界记录最小化审计信息。

    只记录工具名、结果状态、耗时和资源 ID，不记录入参或完整结果，避免把
    用例文本、工具结果或凭证复制到日志。这里覆盖 FastMCP 的统一调用入口，
    因而 ping 和后续新增工具也不会漏记。
    """

    def __init__(self, *args: Any, principal: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._principal = principal

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> Sequence[ContentBlock] | dict[str, object]:
        started = perf_counter()
        input_refs = _resource_refs(arguments)
        try:
            result = await super().call_tool(name, arguments)
        except Exception as exc:
            _LOGGER.warning(
                "mcp_tool_call principal=%s tool=%s status=failed duration_ms=%.2f refs=%s error=%s",
                self._principal,
                name,
                (perf_counter() - started) * 1000,
                ",".join(input_refs) or "-",
                type(exc).__name__,
            )
            raise
        refs = sorted({*input_refs, *_resource_refs(result)})
        _LOGGER.info(
            "mcp_tool_call principal=%s tool=%s status=completed duration_ms=%.2f refs=%s",
            self._principal,
            name,
            (perf_counter() - started) * 1000,
            ",".join(refs) or "-",
        )
        return result


def _resource_refs(value: object) -> list[str]:
    """从 MCP 边界对象中提取可关联资源 ID，不保留原对象。"""

    refs: set[str] = set()

    def collect(item: object) -> None:
        if isinstance(item, BaseModel):
            collect(item.model_dump(mode="json"))
        elif isinstance(item, Mapping):
            # 字段名（如 case_id、profile_snapshot）不是资源 ID，只扫描值。
            for nested in item.values():
                collect(nested)
        elif isinstance(item, Sequence) and not isinstance(
            item,
            (str, bytes, bytearray),
        ):
            for nested in item:
                collect(nested)
        elif isinstance(item, str):
            try:
                decoded: Any = json.loads(item)
            except (json.JSONDecodeError, TypeError):
                decoded = item
            if decoded is not item:
                collect(decoded)
                return
            refs.update(_RESOURCE_ID.findall(item))

    collect(value)
    return sorted(refs)


def create_mcp_server(services: ServiceContainer | None = None) -> FastMCP:
    """为每个 ASGI App 创建独立 session manager，支持测试和应用重建。"""

    server = AuditedFastMCP(
        "agentrig",
        principal="external_controller",
        stateless_http=True,
        streamable_http_path="/",
    )

    @server.tool()
    def ping() -> str:
        """健康检查 —— 返回 'pong'。"""
        return "pong"

    if services is not None:
        register_v1_tools(server, services)
    return server


def create_role_mcp_servers(services: ServiceContainer) -> dict[str, FastMCP]:
    """每个 Agent 身份拥有独立工具注册表，权限不依赖 Prompt。"""

    registrations = {
        "manager": register_manager_tools,
        "curator": register_curator,
        "judge": register_judge,
    }
    servers: dict[str, FastMCP] = {}
    configured_hosts = services.settings.agentteams.mcp_allowed_hosts
    transport_security = (
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
                *configured_hosts,
            ],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
            ],
        )
        if configured_hosts
        else None
    )
    for role, register in registrations.items():
        server = AuditedFastMCP(
            f"agentrig-{role}",
            principal=f"agentteams_{role}",
            stateless_http=True,
            streamable_http_path="/",
            transport_security=transport_security,
        )
        register(server, services)
        servers[role] = server
    return servers


mcp: FastMCP = create_mcp_server()


def build_mcp_app(server: FastMCP | None = None) -> ASGIApp:
    """返回 streamable-HTTP ASGI app，供 FastAPI 挂载到 /mcp。"""
    resolved = server or mcp
    return cast(ASGIApp, resolved.streamable_http_app())


@asynccontextmanager
async def mcp_lifespan(server: FastMCP | None = None) -> AsyncIterator[None]:
    """启动 FastMCP session manager 的 task group（streamable HTTP 必需）。

    必须嵌套在 FastAPI app lifespan 内使用。
    """
    resolved = server or mcp
    async with resolved.session_manager.run():
        yield
