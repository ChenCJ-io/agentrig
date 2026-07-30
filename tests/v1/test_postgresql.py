"""可选 PostgreSQL Repository 集成测试。

只有显式提供名称中包含 ``test`` 的数据库 URL 才运行，避免误删普通数据库表。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.engine import make_url

from agentrig.cases import TestCaseCreate
from agentrig.cases.service import CaseService
from agentrig.infrastructure.database import Database
from agentrig.infrastructure.database.repositories import SqlCaseRepository


async def test_postgresql_case_repository_round_trip() -> None:
    raw_url = os.environ.get("AGENTRIG_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("AGENTRIG_TEST_POSTGRES_URL is not configured")
    database_name = make_url(raw_url).database or ""
    if "test" not in database_name.lower():
        pytest.skip("PostgreSQL integration database name must contain 'test'")

    database = Database(raw_url)
    await database.drop_schema()
    await database.create_schema()
    try:
        service = CaseService(SqlCaseRepository(database))
        created = await service.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_postgresql",
                    "name": "PostgreSQL",
                    "tags": ["cap.search"],
                    "primary_evaluator": "external_controller",
                    "turns": [{"position": 1, "user_message": "hello"}],
                }
            )
        )
        loaded = await service.get(created.id)
        assert loaded.model_dump(mode="json") == created.model_dump(mode="json")
        assert (await service.list_cases()).total == 1
    finally:
        await database.drop_schema()
        await database.dispose()
