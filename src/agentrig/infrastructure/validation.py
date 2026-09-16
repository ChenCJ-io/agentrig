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

    _walk_for_plaintext_secrets(value, path=path, in_json_schema=False)
    return value


def _walk_for_plaintext_secrets(
    value: object,
    *,
    path: str,
    in_json_schema: bool,
) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            current_path = f"{path}.{key}"
            nested_is_schema = in_json_schema or normalized in {
                "input_schema",
                "inputschema",
                "output_schema",
                "outputschema",
                "result_schema",
                "resultschema",
                "tool_arguments_schema",
                "tool_result_schema",
            }
            # JSON Schema 的 properties 键是业务字段名称，不是持久化的字段值。
            # 例如 retrieval_token: {"type": "string"} 可以安全描述参数结构；
            # match_arguments.retrieval_token: "明文值" 仍会被下面的普通路径拒绝。
            property_name = in_json_schema and normalized == "properties"
            if (
                normalized in _SENSITIVE_NAMES
                or normalized.endswith(_SENSITIVE_SUFFIXES)
            ):
                raise ValueError(
                    f"{current_path} may contain a plaintext secret; use secret_ref"
                )
            if property_name and isinstance(nested, dict):
                for property_key, property_schema in nested.items():
                    _walk_for_plaintext_secrets(
                        property_schema,
                        path=f"{current_path}.{property_key}",
                        in_json_schema=True,
                    )
            else:
                _walk_for_plaintext_secrets(
                    nested,
                    path=current_path,
                    in_json_schema=nested_is_schema,
                )
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk_for_plaintext_secrets(
                nested,
                path=f"{path}[{index}]",
                in_json_schema=in_json_schema,
            )
