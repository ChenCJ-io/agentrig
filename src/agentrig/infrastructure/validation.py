"""可持久化任意 JSON 配置的安全校验。"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")

_SENSITIVE_NAMES = {
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "token",
}
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_password",
    "_secret",
    "_token",
)


def reject_plaintext_secrets(value: T, *, path: str) -> T:
    """拒绝写入看起来像凭据的键，避免 Secret 绕过 ``secret_ref``。"""

    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            current_path = f"{path}.{key}"
            if normalized in _SENSITIVE_NAMES or normalized.endswith(
                _SENSITIVE_SUFFIXES
            ):
                raise ValueError(
                    f"{current_path} may contain a plaintext secret; use secret_ref"
                )
            reject_plaintext_secrets(nested, path=current_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            reject_plaintext_secrets(nested, path=f"{path}[{index}]")
    return value
