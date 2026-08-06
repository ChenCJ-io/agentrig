"""Target HTTP 出站策略的 DNS 与 allowlist 边界。"""

from __future__ import annotations

import socket

import pytest

from agentrig.config import TargetNetworkConfig
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.infrastructure.http_policy import TargetHttpPolicy


async def test_hostname_resolving_to_private_address_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def private_result(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("10.0.0.8", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private_result)
    policy = TargetHttpPolicy(TargetNetworkConfig(allowed_hosts=[]))

    with pytest.raises(AgentRigError) as exc:
        await policy.authorize_url("https://target.example.test")

    assert exc.value.detail.code is ErrorCode.PERMISSION_DENIED
    assert exc.value.detail.details == {"target_url_rejected": True}


async def test_explicit_wildcard_allowlist_skips_private_dns_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_lookup(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("allowlisted hosts should not be resolved by the policy")

    monkeypatch.setattr(socket, "getaddrinfo", unexpected_lookup)
    policy = TargetHttpPolicy(
        TargetNetworkConfig(allowed_hosts=["*.trusted.example"])
    )

    await policy.authorize_url("https://agent.trusted.example/v1")


def test_target_url_rejects_userinfo_without_echoing_it() -> None:
    policy = TargetHttpPolicy(TargetNetworkConfig(allowed_hosts=[]))

    with pytest.raises(AgentRigError) as exc:
        policy.validate_url("https://user:super-secret@target.example/v1")

    assert exc.value.detail.code is ErrorCode.PERMISSION_DENIED
    assert "super-secret" not in str(exc.value.detail)
