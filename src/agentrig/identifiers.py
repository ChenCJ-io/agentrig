"""可排序、无中心依赖的 V1 实体标识生成。"""

from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str) -> str:
    """生成便于人工识别的随机 ID。

    UUID 的随机部分保证单进程和多进程部署都无需共享计数器。数据库稳定排序使用
    ``created_at`` 后再使用该 ID，不依赖 ID 自身携带时间。
    """

    return f"{prefix}_{uuid4().hex}"
