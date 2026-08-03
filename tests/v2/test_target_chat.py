"""工作台 Target 直连会话的 Driver/Provider/API 闭环。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from agentrig.app import create_app
from agentrig.bootstrap import ServiceContainer
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)
from agentrig.tool_results import SampleStatus


class TargetChatDriver:
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        assert context.version == "v1"
        assert context.initial_state == {"workspace": "demo"}
        return DriverSession(id="driver-chat-session")

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        del session
        yield DriverEvent(
            type=DriverEventType.SESSION_STARTED,
            session_id="driver-chat-session",
        )
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[
                ToolCall(
                    id="call-chat",
                    name="search",
                    arguments={"q": message, "api_token": "must-not-leak"},
                )
            ],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session
        assert results[0].source == "sample"
        assert results[0].result == {"items": ["matched"]}
        yield DriverEvent(type=DriverEventType.ASSISTANT_TEXT_DELTA, text="已经完成检索。")
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        del session

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True


def test_target_chat_api_runs_real_driver_and_provider_chain() -> None:
    registry = DriverRegistry()
    registry.register("target_chat_test", TargetChatDriver)
    container = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
    )
    with TestClient(create_app(container)) as client:
        assert client.post(
            "/api/targets",
            json={
                "id": "target-chat-test",
                "name": "Target Chat Test",
                "driver_type": "target_chat_test",
                "options": {"conversation_initial_state": {"workspace": "demo"}},
                "versions": [{"version": "v1"}],
            },
        ).status_code == 201
        assert client.post(
            "/api/execution-profiles",
            json={
                "id": "profile-chat-test",
                "name": "Target Chat Profile",
                "config": {
                    "tool_mode": "controlled",
                    "provider_chain": [{"name": "sample"}],
                },
            },
        ).status_code == 201
        sample = client.post(
            "/api/samples",
            json={
                "id": "sample-chat-test",
                "name": "Chat search result",
                "tool_name": "search",
                "match_arguments": {"q": "hello"},
                "ignored_argument_paths": ["api_token"],
                "supported_versions": ["v1"],
                "content": {"items": ["matched"]},
            },
        )
        assert sample.status_code == 201
        approved = client.post(
            "/api/samples/sample-chat-test/review",
            params={"sample_status": SampleStatus.APPROVED.value},
        )
        assert approved.status_code == 200

        created = client.post(
            "/api/v2/target-chats",
            json={
                "target_id": "target-chat-test",
                "profile_id": "profile-chat-test",
            },
        )
        assert created.status_code == 201
        assert created.json()["status"] == "open"
        chat_id = created.json()["id"]

        response = client.post(
            f"/api/v2/target-chats/{chat_id}/messages",
            json={"content": "hello"},
        )
        assert response.status_code == 200
        events = response.json()["events"]
        assert events[-1]["event_type"] == "assistant_message"
        assert events[-1]["payload"]["text"] == "已经完成检索。"
        tool_call = next(item for item in events if item["event_type"] == "tool_call")
        assert tool_call["payload"]["arguments"]["api_token"] == "[REDACTED]"
        assert any(item["event_type"] == "provider_attempt" for item in events)
        assert any(item["event_type"] == "tool_result" for item in events)

        history = client.get(
            "/api/v2/target-chats",
            params={"target_id": "target-chat-test"},
        )
        assert history.status_code == 200
        assert history.json()["total"] == 1
        assert history.json()["items"][0]["id"] == chat_id

        draft_case = client.post(
            f"/api/v2/target-chats/{chat_id}/draft-case",
            json={"name": "Conversation regression", "tags": ["cap.search"]},
        )
        assert draft_case.status_code == 201
        assert draft_case.json()["review_status"] == "draft"
        assert draft_case.json()["supported_versions"] == ["v1"]
        assert draft_case.json()["turns"][0]["fixtures"][0]["result"] == {
            "items": ["matched"]
        }

        draft_sample = client.post(
            f"/api/v2/target-chats/{chat_id}/draft-sample",
            json={"tool_call_id": "call-chat"},
        )
        assert draft_sample.status_code == 201
        assert draft_sample.json()["status"] == "draft"
        assert draft_sample.json()["match_arguments"] == {"q": "hello"}
        assert draft_sample.json()["ignored_argument_paths"] == ["api_token"]

        closed = client.post(f"/api/v2/target-chats/{chat_id}/close")
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"

        persisted = client.get(f"/api/v2/target-chats/{chat_id}")
        assert persisted.status_code == 200
        assert persisted.json()["events"][-1]["event_type"] == "session_closed"
