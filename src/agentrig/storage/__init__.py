"""用例存储：默认内存，配 database.url 走 SQLite 持久化。"""

from __future__ import annotations

import threading

from ..config import get_settings
from .protocol import TestCaseRepo
from .repo import InMemoryTestCaseRepo
from .sqlite_repo import SqliteTestCaseRepo

__all__ = ["InMemoryTestCaseRepo", "SqliteTestCaseRepo", "TestCaseRepo", "get_repo"]

_repo: TestCaseRepo | None = None
_lock = threading.Lock()


def get_repo() -> TestCaseRepo:
    """全局仓库单例（double-checked locking，线程安全）。"""
    global _repo
    if _repo is None:
        with _lock:
            if _repo is None:
                url = get_settings().database.url
                _repo = SqliteTestCaseRepo(url) if url else InMemoryTestCaseRepo()
    return _repo


def reset_repo() -> None:
    """清空单例（测试隔离用）。"""
    global _repo
    with _lock:
        _repo = None
