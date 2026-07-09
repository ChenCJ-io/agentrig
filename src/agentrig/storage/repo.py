"""in-memory 用例存储（默认后端；满足 TestCaseRepo Protocol）。

测试可直接 new InMemoryTestCaseRepo() 建独立实例避免污染全局。
运行时单例由 storage.get_repo() 提供（按配置选内存/SQLite）。
"""
from __future__ import annotations

from ..models import TestCase


class InMemoryTestCaseRepo:
    """简单的内存用例仓库，按 id 索引（满足 TestCaseRepo Protocol）。"""

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
