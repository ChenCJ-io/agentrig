from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentrig.assistant import AssistantSessionCreate
from agentrig.cases import CaseService, TestCaseCreate
from agentrig.cases import TestTurn as CaseTurnSpec
from agentrig.errors import AgentRigError
from agentrig.infrastructure.database.repositories import (
    SqlAssistantRepository,
    SqlCaseRepository,
    SqlTargetChatRepository,
)
from agentrig.infrastructure.database.session import Database
from agentrig.projects import ProjectApiKeyCreate, ProjectCreate, ProjectService
from agentrig.target_chat import TargetChatEvent, TargetChatView


@pytest.mark.asyncio
async def test_project_scoped_repositories_hide_ids_lists_events_and_cursors() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    projects = ProjectService(database)
    await projects.ensure_default()
    other = await projects.create(ProjectCreate(slug="tenant-b", name="Tenant B"))
    default_repository = SqlAssistantRepository(database, project_id="default")
    other_repository = SqlAssistantRepository(database, project_id=other.id)
    try:
        default_session = await default_repository.create_session(
            "assistant_default",
            AssistantSessionCreate(title="Default session"),
            created_by="default-user",
        )
        other_session = await other_repository.create_session(
            "assistant_other",
            AssistantSessionCreate(title="Other session"),
            created_by="other-user",
        )
        assert await default_repository.get_session(other_session.id) is None
        assert await other_repository.get_session(default_session.id) is None
        assert (await default_repository.list_sessions(limit=20, offset=0)).total == 1
        assert (await other_repository.list_sessions(limit=20, offset=0)).total == 1

        event, turn = await default_repository.create_user_message(
            event_id="assistant_event_default",
            turn_id="assistant_turn_default",
            session_id=default_session.id,
            client_message_id="message-default",
            actor_id="default-user",
            content="run evaluation",
            active_plan_id=None,
        )
        assert await other_repository.get_event(event.id) is None
        assert await other_repository.get_turn(turn.id) is None
        assert (
            await other_repository.list_events(
                default_session.id,
                after_seq=0,
                limit=20,
            )
        ).total == 0

        await default_repository.save_integration_cursor("matrix", "default-cursor", {})
        await other_repository.save_integration_cursor("matrix", "other-cursor", {})
        assert await default_repository.get_integration_cursor("matrix") == "default-cursor"
        assert await other_repository.get_integration_cursor("matrix") == "other-cursor"

        default_case_repository = SqlCaseRepository(database, project_id="default")
        other_case_repository = SqlCaseRepository(database, project_id=other.id)
        default_cases = CaseService(default_case_repository)
        case = await default_cases.create(
            TestCaseCreate(
                id="case_default_only",
                name="Default-only case",
                primary_evaluator="rule",
                turns=[CaseTurnSpec(position=1, user_message="hello")],
            )
        )
        assert await other_case_repository.get(case.id) is None

        now = datetime.now(timezone.utc)
        default_chats = SqlTargetChatRepository(database, project_id="default")
        other_chats = SqlTargetChatRepository(database, project_id=other.id)
        chat = TargetChatView(
            id="chat_default",
            target_id="target_default",
            profile_id=None,
            version=None,
            status="open",
            events=[
                TargetChatEvent(
                    seq=1,
                    event_type="user_message",
                    payload={"content": "safe"},
                    created_at=now,
                )
            ],
            created_at=now,
            updated_at=now,
        )
        await default_chats.save(chat)
        assert await other_chats.get(chat.id) is None
        assert (await other_chats.list_page(target_id=None, limit=20, offset=0)).total == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_project_api_keys_enforce_project_and_operation_scope() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    projects = ProjectService(database)
    await projects.ensure_default()
    other = await projects.create(ProjectCreate(slug="scope-b", name="Scope B"))
    try:
        issue = await projects.issue_api_key(
            "default",
            ProjectApiKeyCreate(name="reader", scopes=["read"]),
        )
        context = await projects.authenticate("default", issue.token, "read")
        assert context.project_id == "default"
        with pytest.raises(AgentRigError):
            await projects.authenticate("default", issue.token, "run")
        with pytest.raises(AgentRigError):
            await projects.authenticate(other.id, issue.token, "read")
    finally:
        await database.dispose()
