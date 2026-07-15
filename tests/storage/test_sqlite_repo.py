"""SQLite 持久化存储测试。"""
from __future__ import annotations

import pytest

from agentrig.models import TestCase
from agentrig.storage.sqlite_repo import SqliteTestCaseRepo


def _case(cid: str) -> TestCase:
    return TestCase(
        id=cid, name=cid, user_message=f"msg-{cid}", expected_tools=["t"], mock={"t": "r"}
    )


def test_sqlite_upsert_get(tmp_path: object) -> None:
    repo = SqliteTestCaseRepo(str(tmp_path / "cases.db"))  # type: ignore[operator]
    repo.upsert(_case("c1"))
    got = repo.get("c1")
    assert got is not None
    assert got.user_message == "msg-c1"
    assert got.expected_tools == ["t"]
    assert got.mock == {"t": "r"}


def test_sqlite_list_and_overwrite(tmp_path: object) -> None:
    repo = SqliteTestCaseRepo(str(tmp_path / "c.db"))  # type: ignore[operator]
    repo.upsert(_case("c1"))
    repo.upsert(_case("c2"))
    assert {c.id for c in repo.list_all()} == {"c1", "c2"}
    # 覆盖同 id
    repo.upsert(TestCase(id="c1", name="c1", user_message="updated"))
    assert repo.get("c1").user_message == "updated"
    assert len(repo.list_all()) == 2  # 仍 2 条（覆盖非新增）


def test_sqlite_delete_and_clear(tmp_path: object) -> None:
    repo = SqliteTestCaseRepo(str(tmp_path / "c.db"))  # type: ignore[operator]
    repo.upsert(_case("c1"))
    repo.upsert(_case("c2"))
    assert repo.delete("c1") is True
    assert repo.delete("missing") is False
    assert {c.id for c in repo.list_all()} == {"c2"}
    repo.clear()
    assert repo.list_all() == []


def test_sqlite_get_missing(tmp_path: object) -> None:
    repo = SqliteTestCaseRepo(str(tmp_path / "c.db"))  # type: ignore[operator]
    assert repo.get("nope") is None


def test_sqlite_persists_across_instances(tmp_path: object) -> None:
    """新实例重开同一文件，数据仍在（持久化核心）。"""
    db = str(tmp_path / "persist.db")  # type: ignore[operator]
    repo1 = SqliteTestCaseRepo(db)
    repo1.upsert(_case("c1"))
    repo1.close()

    repo2 = SqliteTestCaseRepo(db)
    got = repo2.get("c1")
    assert got is not None
    assert got.user_message == "msg-c1"


def test_sqlite_rejects_path_traversal() -> None:
    """database url 含 .. 时拒绝（防穿越到任意位置写文件）。"""
    with pytest.raises(ValueError):
        SqliteTestCaseRepo("../evil.db")
    with pytest.raises(ValueError):
        SqliteTestCaseRepo("sqlite:///../../etc/evil")
