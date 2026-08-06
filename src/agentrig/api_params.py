"""HTTP 查询参数的统一资源边界。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

PageLimit = Annotated[int, Query(ge=1, le=200)]
EventLimit = Annotated[int, Query(ge=1, le=500)]
PageOffset = Annotated[int, Query(ge=0)]
EventSequence = Annotated[int, Query(ge=0)]
