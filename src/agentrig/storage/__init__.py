"""用例存储（v0.1 in-memory；后续接 DB）。"""

from .repo import InMemoryTestCaseRepo, get_repo

__all__ = ["InMemoryTestCaseRepo", "get_repo"]
