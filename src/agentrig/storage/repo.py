"""in-memory 用例存储（v0.1 骨架；后续接 DB）。

模块级单例通过 get_repo() 获取（运行时）。测试可直接 new InMemoryTestCaseRepo()
建独立实例避免污染全局。
"""
from __future__ import annotations

from ..models import TestCase


class InMemoryTestCaseRepo:
    """简单的内存用例仓库，按 id 索引。"""

    def __init__(self) -> None:
        self._cases: dict[str, TestCase] = {}

    def upsert(self, case: TestCase) -> TestCase:
        """创建或更新用例（按 id 覆盖）。"""
        self._cases[case.id] = case
        return case

    def get(self, case_id: str) -> TestCase | None:
        """按 id 取用例；不存在返回 None。"""
        return self._cases.get(case_id)

    def list_all(self) -> list[TestCase]:
        """返回所有用例。"""
        return list(self._cases.values())

    def delete(self, case_id: str) -> bool:
        """删除用例；存在并删除返回 True，否则 False。"""
        return self._cases.pop(case_id, None) is not None

    def clear(self) -> None:
        """清空（测试用）。"""
        self._cases.clear()


# 模块级单例（运行时用；测试建独立实例）
_repo = InMemoryTestCaseRepo()


def get_repo() -> InMemoryTestCaseRepo:
    """全局仓库单例。"""
    return _repo
