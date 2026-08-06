"""Target HTTP 出站访问策略，限制 SSRF 可达范围。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import NoReturn
from urllib.parse import urlsplit

from ..config import TargetNetworkConfig
from ..errors import AgentRigError, ErrorCode


class TargetHttpPolicy:
    def __init__(self, config: TargetNetworkConfig | None = None) -> None:
        resolved = config or TargetNetworkConfig()
        self._allow_private_networks = resolved.allow_private_networks
        self._allowed_hosts = tuple(item.lower().rstrip(".") for item in resolved.allowed_hosts)

    def validate_url(self, value: str) -> str:
        """校验 URL 结构和无需 DNS 即可判断的网络边界。"""

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            self._reject(value, "Target endpoint must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            self._reject(value, "Target endpoint must not contain userinfo")
        try:
            parsed.port
        except ValueError:
            self._reject(value, "Target endpoint contains an invalid port")
        host = parsed.hostname.lower().rstrip(".")
        if self._host_is_allowed(host) or self._allow_private_networks:
            return host
        if host == "localhost" or host.endswith(".localhost"):
            self._reject(value, "private Target endpoints are not allowed")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return host
        if not address.is_global:
            self._reject(value, "private Target endpoints are not allowed")
        return host

    async def authorize_url(self, value: str) -> None:
        """在发请求前解析 DNS，拒绝解析到非公网地址的未授权主机。"""

        host = self.validate_url(value)
        if self._host_is_allowed(host) or self._allow_private_networks:
            return
        parsed = urlsplit(value)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise AgentRigError(
                ErrorCode.TARGET_UNREACHABLE,
                f"Target endpoint host cannot be resolved: {host}",
                retryable=True,
            ) from exc
        addresses = {ipaddress.ip_address(item[4][0]) for item in infos}
        if not addresses or any(not address.is_global for address in addresses):
            self._reject(value, "Target endpoint resolves to a private network address")

    def _host_is_allowed(self, host: str) -> bool:
        for pattern in self._allowed_hosts:
            if pattern.startswith("*."):
                suffix = pattern[1:]
                if host.endswith(suffix) and host != suffix[1:]:
                    return True
            elif host == pattern:
                return True
        return False

    @staticmethod
    def _reject(_value: str, message: str) -> NoReturn:
        raise AgentRigError(
            ErrorCode.PERMISSION_DENIED,
            message,
            details={"target_url_rejected": True},
        )
