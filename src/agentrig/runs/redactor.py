"""运行证据落库前的递归脱敏。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast


class Redactor:
    def __init__(
        self,
        *,
        sensitive_keys: list[str] | None = None,
        sensitive_paths: list[str] | None = None,
    ) -> None:
        self._sensitive_keys = {
            value.lower()
            for value in (
                sensitive_keys
                or ["authorization", "cookie", "api_key", "token", "secret"]
            )
        }
        self._sensitive_paths = set(sensitive_paths or [])

    def redact(
        self,
        payload: dict[str, Any],
        *,
        extra_sensitive_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        paths = self._sensitive_paths | set(extra_sensitive_paths or [])
        value = deepcopy(payload)
        return cast(
            "dict[str, Any]",
            self._walk(value, path="", sensitive_paths=paths),
        )

    def _walk(self, value: Any, *, path: str, sensitive_paths: set[str]) -> Any:
        if path in sensitive_paths:
            return "[REDACTED]"
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, item in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if self._is_sensitive_key(str(key)) or child_path in sensitive_paths:
                    output[str(key)] = "[REDACTED]"
                else:
                    output[str(key)] = self._walk(
                        item,
                        path=child_path,
                        sensitive_paths=sensitive_paths,
                    )
            return output
        if isinstance(value, list):
            return [
                self._walk(
                    item,
                    path=f"{path}.{index}" if path else str(index),
                    sensitive_paths=sensitive_paths,
                )
                for index, item in enumerate(value)
            ]
        return value

    def _is_sensitive_key(self, key: str) -> bool:
        normalized = key.lower()
        return (
            normalized in self._sensitive_keys
            or normalized.endswith("_token")
            or normalized.endswith("_secret")
            or normalized.endswith("_api_key")
        )
