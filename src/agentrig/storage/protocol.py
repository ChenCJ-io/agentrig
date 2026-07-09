"""用例存储的抽象接口。InMemory / SQLite 等实现都满足此 Protocol。"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import TestCase


@runtime_checkable
class TestCaseRepo(Protocol):
    """测试用例仓库接口。"""

    def upsert(self, case: TestCase) -> TestCase: ...

    def get(self, case_id: str) -> TestCase | None: ...

    def list_all(self) -> list[TestCase]: ...

    def delete(self, case_id: str) -> bool: ...

    def clear(self) -> None: ...
