"""Target 基础配置与版本覆盖配置的合并规则。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def merge_target_options(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """递归合并对象字段；版本值覆盖基础值，数组和标量整体替换。

    这样版本配置只需填写真正变化的字段，例如
    ``device_info.app_version``，无需复制 device_id、os 等公共信息。
    """

    merged = deepcopy(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_target_options(current, value)
        else:
            merged[key] = deepcopy(value)
    return merged
