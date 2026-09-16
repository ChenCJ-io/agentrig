"""冒烟测试：MCP server 通过 streamable HTTP 响应 ping。"""
from __future__ import annotations

import json

from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database


def _jsonrpc(req_id: int, method: str, params: dict | None = None) -> dict:
    payload: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _parse_sse_json(body: str) -> dict:
    """从 SSE 响应体里提取最后一条 `data:` 的 JSON。"""
    for line in reversed(body.splitlines()):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no data line in SSE body:\n{body}")


async def test_mcp_ping() -> None:
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
    )
    app = create_app(services)
    # LifespanManager 驱动 FastAPI lifespan，启动 MCP session manager 的
    # task group（ASGITransport 本身不跑 lifespan）。
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://localhost:8000",
            follow_redirects=True,
            headers={"Accept": "application/json, text/event-stream"},
        ) as client:
            # initialize 握手
            init = await client.post(
                "/mcp/",
                json=_jsonrpc(
                    1,
                    "initialize",
                    {
                        "protocolVersion": "2025-06-18",
                        "clientInfo": {"name": "test", "version": "0"},
                        "capabilities": {},
                    },
                ),
            )
            assert init.status_code == 200, init.text

            call = await client.post(
                "/mcp/",
                json=_jsonrpc(2, "tools/call", {"name": "ping", "arguments": {}}),
            )
            assert call.status_code == 200, call.text
            body = _parse_sse_json(call.text)
            assert body["result"]["content"][0]["text"] == "pong", body
