"""所有 Provider 共用的确定性工具结果 Validator。"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator


class ToolResultValidation:
    def __init__(self, valid: bool, errors: list[str]) -> None:
        self.valid = valid
        self.errors = errors


class ToolResultValidator:
    def __init__(
        self,
        *,
        max_bytes: int = 1_000_000,
        forbidden_keys: list[str] | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._forbidden_keys = {
            value.lower()
            for value in (
                forbidden_keys
                or ["authorization", "cookie", "api_key", "access_token", "secret"]
            )
        }

    def validate(
        self,
        result: Any,
        *,
        result_schema: dict[str, Any] | None,
    ) -> ToolResultValidation:
        errors: list[str] = []
        try:
            encoded = json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
        except (TypeError, ValueError) as exc:
            return ToolResultValidation(False, [f"result is not JSON serializable: {exc}"])
        if len(encoded) > self._max_bytes:
            errors.append(
                f"result exceeds maximum size: {len(encoded)} > {self._max_bytes} bytes"
            )
        sensitive = sorted(self._find_forbidden_keys(result))
        if sensitive:
            errors.append(f"result contains forbidden sensitive fields: {sensitive}")
        if result_schema:
            validator = Draft202012Validator(result_schema)
            errors.extend(
                f"{'/'.join(str(part) for part in error.path) or '$'}: {error.message}"
                for error in sorted(validator.iter_errors(result), key=lambda item: list(item.path))
            )
        return ToolResultValidation(not errors, errors)

    def _find_forbidden_keys(self, value: Any, path: str = "") -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                key_path = f"{path}.{key}" if path else str(key)
                normalized = str(key).lower()
                if normalized in self._forbidden_keys or normalized.endswith("_secret"):
                    found.add(key_path)
                else:
                    found.update(self._find_forbidden_keys(item, key_path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                found.update(self._find_forbidden_keys(item, f"{path}.{index}"))
        return found
