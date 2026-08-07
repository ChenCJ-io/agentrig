"""正式 Driver 协议归一和实验 subprocess 契约。"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from agentrig.errors import AgentRigError
from agentrig.targets.drivers import (
    DriverCapabilities,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    HttpSseDriver,
    OpenAICompatibleDriver,
    PixcakeHttpSseDriver,
    SubprocessDriver,
    ToolResult,
)
from agentrig.targets.drivers.http_sse import parse_sse_line


def context(
    *,
    endpoint: str | None = "http://agent.test/v1",
    options: dict[str, object] | None = None,
    secret_value: str | None = None,
) -> DriverPrepareContext:
    return DriverPrepareContext(
        case_run_id="cr",
        target={
            "endpoint": endpoint,
            "options": options or {},
        },
        version="v1",
        initial_state={"tenant": "demo"},
        secret_value=secret_value,
        component_timeout_seconds=10,
    )


def test_http_sse_parser_normalizes_supported_events() -> None:
    request_started = parse_sse_line(
        'data: {"type":"request_started","data":{'
        '"request_id":"r1","request_kind":"chat"}}'
    )
    session = parse_sse_line(
        'data: {"type":"session_created","data":{'
        '"session_id":"s1","request_id":"r1"}}'
    )
    call = parse_sse_line(
        'data: {"type":"tool_calls","data":{"tool_calls":['
        '{"id":"c1","name":"search","input":{"q":"x"}}]}}'
    )
    done = parse_sse_line("data: [DONE]")
    refusal = parse_sse_line(
        'data: {"type":"assistant_message_completed",'
        '"data":{"text":"cannot comply","refusal":true}}'
    )
    request_completed = parse_sse_line(
        'data: {"type":"request_completed","data":{'
        '"request_id":"r1","request_kind":"chat",'
        '"request_status":"completed","duration_ms":1.5}}'
    )
    assert request_started is not None
    assert request_started.type is DriverEventType.REQUEST_STARTED
    assert request_started.request_id == "r1"
    assert session is not None and session.type is DriverEventType.SESSION_STARTED
    assert session.request_id == "r1"
    assert call is not None and call.tool_calls[0].arguments == {"q": "x"}
    assert done is not None and done.type is DriverEventType.COMPLETED
    assert refusal is not None and refusal.refusal is True
    assert request_completed is not None
    assert request_completed.type is DriverEventType.REQUEST_COMPLETED
    assert request_completed.duration_ms == 1.5
    assert HttpSseDriver().capabilities().tool_result_injection is True


async def test_openai_driver_continues_after_tool_result() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"body": body, "auth": request.headers.get("authorization")})
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"q":"hello"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                    "usage": {"total_tokens": 10},
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "finished",
                        }
                    }
                ]
            },
        )

    driver = OpenAICompatibleDriver(transport=httpx.MockTransport(handler))
    session = await driver.prepare(
        context(options={"model": "agent-model"}, secret_value="secret")
    )
    first = [event async for event in driver.send_user_message(session, "hello")]
    assert first[0].type is DriverEventType.USAGE
    assert first[1].type is DriverEventType.TOOL_CALLS
    assert first[1].tool_calls[0].arguments == {"q": "hello"}
    second = [
        event
        async for event in driver.send_tool_results(
            session,
            [
                ToolResult(
                    tool_call_id="call_1",
                    tool_name="search",
                    result={"items": []},
                    source="fixture",
                )
            ],
        )
    ]
    assert [event.type for event in second] == [
        DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
        DriverEventType.COMPLETED,
    ]
    assert requests[0]["auth"] == "Bearer secret"
    second_messages = requests[1]["body"]["messages"]  # type: ignore[index]
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_call_id"] == "call_1"


async def test_subprocess_driver_uses_allowlisted_jsonl_protocol() -> None:
    script = """
import json, sys
for line in sys.stdin:
    value = json.loads(line)
    if value["type"] == "chat":
        print(json.dumps({"type":"tool_calls","tool_calls":[{"id":"c","name":"search","arguments":{"q":"x"}}]}), flush=True)
    else:
        print(json.dumps({"type":"assistant_message_completed","text":"done"}), flush=True)
        print(json.dumps({"type":"completed"}), flush=True)
"""
    driver = SubprocessDriver(executable_allowlist=[sys.executable])
    session = await driver.prepare(
        context(
            endpoint=None,
            options={"command": [sys.executable, "-u", "-c", script]},
        )
    )
    try:
        first = [event async for event in driver.send_user_message(session, "hello")]
        assert first[0].type is DriverEventType.TOOL_CALLS
        second = [
            event
            async for event in driver.send_tool_results(
                session,
                [
                    ToolResult(
                        tool_call_id="c",
                        tool_name="search",
                        result={"items": []},
                        source="fixture",
                    )
                ],
            )
        ]
        assert [event.type for event in second] == [
            DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            DriverEventType.COMPLETED,
        ]
    finally:
        await driver.close(session)


async def test_http_driver_injects_scoped_proxy_configuration() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            text="data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    driver = HttpSseDriver(transport=httpx.MockTransport(handler))
    prepare_context = context()
    prepare_context.tool_proxy_url = "http://agentrig.test/proxy"
    prepare_context.tool_proxy_headers = {
        "X-AgentRig-Proxy-Scope": "scope_1",
    }
    session = await driver.prepare(prepare_context)
    _ = [event async for event in driver.send_user_message(session, "hello")]

    assert captured["tool_proxy"] == {
        "url": "http://agentrig.test/proxy",
        "headers": {"X-AgentRig-Proxy-Scope": "scope_1"},
    }


async def test_http_driver_normalizes_http_failure_without_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="private upstream diagnostic")

    driver = HttpSseDriver(transport=httpx.MockTransport(handler))
    session = await driver.prepare(context())
    events = [event async for event in driver.send_user_message(session, "hello")]

    assert [event.type for event in events] == [DriverEventType.ERROR]
    assert events[0].error == "target HTTP request failed with status 503"
    assert "private upstream diagnostic" not in (events[0].error or "")


async def test_http_driver_normalizes_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private connection detail", request=request)

    driver = HttpSseDriver(transport=httpx.MockTransport(handler))
    session = await driver.prepare(context())
    events = [event async for event in driver.send_user_message(session, "hello")]

    assert [event.type for event in events] == [DriverEventType.ERROR]
    assert events[0].error == "target HTTP request failed: ConnectError"
    assert "private connection detail" not in (events[0].error or "")


async def test_pixcake_driver_sends_required_identity_on_each_request() -> None:
    requests: list[dict[str, object]] = []
    request_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        request_ids.append(request.headers.get("x-request-id"))
        if len(requests) == 1:
            stream = (
                'data: {"type":"session_created","data":{"session_id":"s1"}}\n\n'
                'data: {"type":"tool_calls","data":{"tool_calls":['
                '{"id":"c1","name":"search","input":{"q":"x"}}]}}\n\n'
            )
        else:
            stream = "data: [DONE]\n\n"
        return httpx.Response(
            200,
            text=stream,
            headers={"content-type": "text/event-stream"},
        )

    driver = PixcakeHttpSseDriver(transport=httpx.MockTransport(handler))
    prepare_context = context(
        options={
            "user_id": 10001,
            "device_info": {
                "device_id": "agentrig",
                "os": "macOS",
                "os_version": "15.7",
                "app_version": "9.2.0",
                "tool_version": 7,
            },
            "chat_channel": "pixcake_client",
            "request_defaults": {
                "metadata": {"project_id": 8},
                "message": "must-not-override",
            },
        }
    )
    prepare_context.initial_state = {
        "pixcake_request": {
            "attachments": [{"type": "image", "image_id": 9}],
            "user_id": 999,
        }
    }
    session = await driver.prepare(prepare_context)
    first = [event async for event in driver.send_user_message(session, "hello")]
    assert [event.type for event in first] == [
        DriverEventType.REQUEST_STARTED,
        DriverEventType.SESSION_STARTED,
        DriverEventType.TOOL_CALLS,
        DriverEventType.REQUEST_COMPLETED,
    ]
    emitted_request_id = first[0].request_id
    assert emitted_request_id
    assert {event.request_id for event in first} == {emitted_request_id}
    assert first[-1].request_status == "completed"
    assert first[-1].duration_ms is not None
    assert first[-1].ttft_ms is not None
    _ = [
        event
        async for event in driver.send_tool_results(
            session,
            [
                ToolResult(
                    tool_call_id="c1",
                    tool_name="search",
                    result={"items": []},
                    source="sample",
                )
            ],
        )
    ]
    _ = [event async for event in driver.send_user_message(session, "again")]

    assert requests[0] == {
        "type": "chat",
        "message": "hello",
        "metadata": {"project_id": 8},
        "attachments": [{"type": "image", "image_id": 9}],
        "user_id": 10001,
        "device_info": {
            "device_id": "agentrig",
            "os": "macOS",
            "os_version": "15.7",
            "app_version": "9.2.0",
            "tool_version": 7,
        },
        "chat_channel": "pixcake_client",
    }
    assert requests[1]["session_id"] == "s1"
    assert requests[1]["user_id"] == 10001
    assert requests[1]["device_info"] == requests[0]["device_info"]
    assert "metadata" not in requests[1]
    assert requests[2]["metadata"] == {"project_id": 8}
    assert requests[2]["session_id"] == "s1"
    assert "attachments" not in requests[2]
    assert len(set(request_ids)) == 3
    assert all(request_ids)
    assert request_ids[0] == emitted_request_id
    capabilities = driver.capabilities()
    assert capabilities.tool_result_injection is True
    assert capabilities.tool_proxy_injection is False
    assert capabilities.usage_metrics is False


async def test_pixcake_driver_rejects_incomplete_client_identity() -> None:
    driver = PixcakeHttpSseDriver()
    with pytest.raises(ValueError, match="user_id"):
        await driver.prepare(context(options={}))
    with pytest.raises(ValueError, match="app_version"):
        await driver.prepare(
            context(
                options={
                    "user_id": 10001,
                    "device_info": {
                        "os": "macOS",
                        "os_version": "15.7",
                    },
                }
            )
        )


def test_python_driver_requires_allowlisted_module_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PluginDriver:
        def capabilities(self) -> DriverCapabilities:
            return DriverCapabilities(multi_turn=True)

    monkeypatch.setattr(
        "agentrig.targets.drivers.registry.importlib.import_module",
        lambda name: SimpleNamespace(PluginDriver=PluginDriver),
    )
    allowed = DriverRegistry(
        python_allowlist=["my_driver:PluginDriver"],
    )
    assert isinstance(
        allowed.create("python", entrypoint="my_driver:PluginDriver"),
        PluginDriver,
    )
    with pytest.raises(AgentRigError, match="allowlist"):
        DriverRegistry().create(
            "python",
            entrypoint="my_driver:PluginDriver",
        )
