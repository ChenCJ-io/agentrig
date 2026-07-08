"""InMemoryTestCaseRepo 单元测试。"""
from __future__ import annotations

from agentrig.models import TestCase
from agentrig.storage import InMemoryTestCaseRepo


def _case(case_id: str = "c1") -> TestCase:
    return TestCase(id=case_id, name="test", user_message="hi")


def test_upsert_and_get() -> None:
    repo = InMemoryTestCaseRepo()
    repo.upsert(_case("c1"))
    c = repo.get("c1")
    assert c is not None
    assert c.id == "c1"
    assert repo.get("missing") is None


def test_list_all() -> None:
    repo = InMemoryTestCaseRepo()
    repo.upsert(_case("c1"))
    repo.upsert(_case("c2"))
    assert {c.id for c in repo.list_all()} == {"c1", "c2"}


def test_upsert_overwrites_by_id() -> None:
    repo = InMemoryTestCaseRepo()
    repo.upsert(TestCase(id="c1", name="old", user_message="a"))
    repo.upsert(TestCase(id="c1", name="new", user_message="b"))
    c = repo.get("c1")
    assert c is not None
    assert c.name == "new"
    assert c.user_message == "b"
    assert len(repo.list_all()) == 1  # 同 id 覆盖，不新增


def test_delete() -> None:
    repo = InMemoryTestCaseRepo()
    repo.upsert(_case("c1"))
    assert repo.delete("c1") is True
    assert repo.get("c1") is None
    assert repo.delete("c1") is False  # 已删


def test_clear() -> None:
    repo = InMemoryTestCaseRepo()
    repo.upsert(_case("c1"))
    repo.upsert(_case("c2"))
    repo.clear()
    assert repo.list_all() == []
