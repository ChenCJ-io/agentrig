"""Sample Provider 的规范化 JSON 精确匹配。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalized_arguments(
    value: dict[str, Any],
    ignored_paths: list[str],
) -> dict[str, Any]:
    result = deepcopy(value)
    for path in ignored_paths:
        _remove_path(result, path.split("."))
    return result


def exact_arguments_match(
    expected: dict[str, Any],
    actual: dict[str, Any],
    ignored_paths: list[str],
) -> bool:
    return normalized_arguments(expected, ignored_paths) == normalized_arguments(
        actual,
        ignored_paths,
    )


def _remove_path(value: Any, parts: list[str]) -> None:
    if not parts:
        return
    head, *tail = parts
    if isinstance(value, dict):
        if not tail:
            value.pop(head, None)
        elif head in value:
            _remove_path(value[head], tail)
    elif isinstance(value, list):
        if head == "*":
            for item in value:
                _remove_path(item, tail)
        elif head.isdigit() and int(head) < len(value):
            _remove_path(value[int(head)], tail)
