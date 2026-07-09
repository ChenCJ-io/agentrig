"""用例存储：默认内存，配 database.url 走 SQLite 持久化。"""

from __future__ import annotations

from ..config import get_settings
from .protocol import TestCaseRepo
from .repo import InMemoryTestCaseRepo
from .sqlite_repo import SqliteTestCaseRepo

__all__ = ["InMemoryTestCaseRepo", "SqliteTestCaseRepo", "TestCaseRepo", "get_repo"]

_repo: TestCaseRepo | None = None


def get_repo() -> TestCaseRepo:
    """全局仓库单例：配了 database.url 用 SQLite，否则内存。"""
    global _repo
    if _repo is None:
        url = get_settings().database.url
        _repo = SqliteTestCaseRepo(url) if url else InMemoryTestCaseRepo()
    return _repo


def reset_repo() -> None:
    """清空单例（测试隔离用）。"""
    global _repo
    _repo = None
