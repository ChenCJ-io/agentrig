"""SQLite 持久化用例存储。

TestCase 序列化为 JSON 存 cases 表（id TEXT PRIMARY KEY, doc TEXT）。
用标准库 sqlite3，无额外依赖。配 AGENTRIG_DATABASE__URL 启用：
- 文件路径（如 ``agentrig.db``）→ 持久化到磁盘
- ``sqlite:///path/to.db`` → 同上（去掉前缀）
- ``:memory:`` → 内存库（测试用，单实例内有效）
"""
from __future__ import annotations

import sqlite3

from ..models import TestCase


class SqliteTestCaseRepo:
    """SQLite 后端的 TestCaseRepo 实现。"""

    def __init__(self, url: str) -> None:
        path = url[len("sqlite://") :].lstrip("/") if url.startswith("sqlite://") else url
        # check_same_thread=False：ASGI 多协程/线程可能共享；连接在单例生命周期内持有
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
        )
        self._conn.commit()

    def upsert(self, case: TestCase) -> TestCase:
        self._conn.execute(
            "INSERT INTO cases (id, doc) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
            (case.id, case.model_dump_json()),
        )
        self._conn.commit()
        return case

    def get(self, case_id: str) -> TestCase | None:
        row = self._conn.execute(
            "SELECT doc FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            return None
        return TestCase.model_validate_json(row[0])

    def list_all(self) -> list[TestCase]:
        rows = self._conn.execute("SELECT doc FROM cases ORDER BY id").fetchall()
        return [TestCase.model_validate_json(r[0]) for r in rows]

    def delete(self, case_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cases")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
