"""可选 PostgreSQL Repository 集成测试。

只有显式提供名称中包含 ``test`` 的数据库 URL 才运行，避免误删普通数据库表。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.engine import make_url

from agentrig.assistant import (
    AssistantMessageCreate,
    AssistantSessionCreate,
    ManagerDecisionProposal,
)
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.cases.service import CaseService
from agentrig.config import Settings
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


async def test_postgresql_serializes_decisions_across_service_instances() -> None:
    raw_url = _postgres_test_url()
    database_a = Database(raw_url)
    database_b = Database(raw_url)
    await database_a.drop_schema()
    await database_a.create_schema()
    settings = Settings(database={"url": raw_url})
    service_a = ServiceContainer.build(settings, database=database_a)
    service_b = ServiceContainer.build(settings, database=database_b)
    try:
        session = await service_a.assistant.create_session(
            AssistantSessionCreate(title="concurrent decisions"),
            created_by="postgres-test",
        )
        message = await service_a.assistant.send_message(
            session.id,
            AssistantMessageCreate(
                client_message_id="postgres-message",
                content="record concurrent decisions",
            ),
            actor_id="postgres-test",
        )

        def proposal(index: int, key: str) -> ManagerDecisionProposal:
            return ManagerDecisionProposal(
                session_id=session.id,
                turn_id=message.turn_id,
                trigger="user_request",
                decision_kind="clarification",
                objective=f"record concurrent decision {index}",
                observation_summary={"known": ["the request event exists"]},
                options=[{"action_type": "no_action", "label": "record only"}],
                selected_action={"action_type": "no_action"},
                rationale_summary={"summary": "No mutation is required."},
                evidence_refs=[
                    {"kind": "assistant_event", "resource_id": message.event_id}
                ],
                idempotency_key=key,
            )

        records = await asyncio.gather(
            service_a.decisions.record(proposal(1, "postgres-decision-1")),
            service_b.decisions.record(proposal(2, "postgres-decision-2")),
            service_a.decisions.record(proposal(3, "postgres-shared")),
            service_b.decisions.record(proposal(3, "postgres-shared")),
        )
        assert records[2].id == records[3].id
        assert sorted({item.ordinal for item in records}) == [1, 2, 3]
        events = await service_a.assistant.list_events(session.id)
        assert len([item for item in events.items if item.decision_id]) == 3
    finally:
        await service_a.close()
        await service_b.close()
        cleanup = Database(raw_url)
        await cleanup.drop_schema()
        await cleanup.dispose()


def _postgres_test_url() -> str:
    raw_url = os.environ.get("AGENTRIG_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("AGENTRIG_TEST_POSTGRES_URL is not configured")
    database_name = make_url(raw_url).database or ""
    if "test" not in database_name.lower():
        pytest.skip("PostgreSQL integration database name must contain 'test'")
    return raw_url
