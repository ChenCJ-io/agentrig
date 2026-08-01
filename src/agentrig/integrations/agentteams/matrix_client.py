"""AgentTeams 内置 Matrix/Tuwunel 的最小 Client-Server API 客户端。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class MatrixClient:
    def __init__(
        self,
        homeserver_url: str,
        access_token: str,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = homeserver_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._timeout = timeout_seconds
        self._transport = transport

    async def versions(self) -> dict[str, Any]:
        return await self._request("GET", "/_matrix/client/versions")

    async def create_room(
        self,
        *,
        name: str,
        topic: str,
        invite: list[str],
    ) -> str:
        response = await self._request(
            "POST",
            "/_matrix/client/v3/createRoom",
            json={
                "preset": "private_chat",
                "name": name,
                "topic": topic,
                "invite": list(dict.fromkeys(item for item in invite if item)),
                "is_direct": False,
                "creation_content": {"org.agentrig.session": True},
            },
        )
        return str(response["room_id"])

    async def send_message(
        self,
        room_id: str,
        transaction_id: str,
        content: dict[str, Any],
    ) -> str:
        room = quote(room_id, safe="")
        txn = quote(transaction_id, safe="")
        response = await self._request(
            "PUT",
            f"/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}",
            json=content,
        )
        return str(response["event_id"])

    async def sync(
        self,
        *,
        since: str | None,
        timeout_ms: int = 20_000,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {"timeout": timeout_ms}
        if since:
            params["since"] = since
        return await self._request(
            "GET",
            "/_matrix/client/v3/sync",
            params=params,
            request_timeout=max(self._timeout, timeout_ms / 1000 + 5),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str | int] | None = None,
        request_timeout: float | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=request_timeout or self._timeout,
            transport=self._transport,
        ) as client:
            response = await client.request(method, path, json=json, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Matrix returned a non-object response")
            return payload
