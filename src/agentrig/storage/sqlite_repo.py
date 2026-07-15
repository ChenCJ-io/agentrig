"""SQLite 持久化用例存储。

TestCase 序列化为 JSON 存 cases 表（id TEXT PRIMARY KEY, doc TEXT）。
用标准库 sqlite3，无额外依赖。配 AGENTRIG_DATABASE__URL 启用：
- 文件路径（如 ``agentrig.db``）→ 持久化到磁盘
- ``sqlite:///path/to.db`` → 同上（去掉前缀）
- ``:memory:`` → 内存库（测试用，单实例内有效）

并发：所有操作加 threading.Lock + WAL 模式 + busy_timeout，ASGI 多协程/线程下安全。
路径：拒绝含 ``..`` 的路径（防穿越到任意位置写文件）。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..models import TestCase


class SqliteTestCaseRepo:
    """SQLite 后端的 TestCaseRepo 实现（线程安全）。"""

    def __init__(self, url: str) -> None:
        path = url[len("sqlite://") :].lstrip("/") if url.startswith("sqlite://") else url
        # 路径穿越防护：拒绝含 .. 的路径（防写到任意位置）
        if path != ":memory:" and ".." in Path(path).parts:
            raise ValueError(f"database path 含 '..'，拒绝：{url}")
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 并发读不阻塞写
        self._conn.execute("PRAGMA busy_timeout=5000")  # 写锁等待 5s
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
        )
        self._conn.commit()
        self._lock = threading.Lock()

    def upsert(self, case: TestCase) -> TestCase:
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases (id, doc) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
                (case.id, case.model_dump_json()),
            )
            self._conn.commit()
        return case

    def get(self, case_id: str) -> TestCase | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT doc FROM cases WHERE id = ?", (case_id,)
            ).fetchone()
        if row is None:
            return None
        return TestCase.model_validate_json(row[0])

    def list_all(self) -> list[TestCase]:
        with self._lock:
            rows = self._conn.execute("SELECT doc FROM cases ORDER BY id").fetchall()
        return [TestCase.model_validate_json(r[0]) for r in rows]

    def delete(self, case_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM cases")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
