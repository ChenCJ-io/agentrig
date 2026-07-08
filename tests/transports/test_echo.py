"""EchoTransport：验证完整的 tool-call 拦截回路。"""
from __future__ import annotations

from agentrig.models import ToolResult
from agentrig.transports.base import EventType, NormalizedEvent
from agentrig.transports.echo import EchoScript, EchoTransport


async def test_echo_tool_call_loop() -> None:
    script = EchoScript(
        on_user_message=[
            [
                NormalizedEvent(type=EventType.TEXT_DELTA, text="let me search"),
                NormalizedEvent(
                    type=EventType.TOOL_CALLS,
                    tool_calls=[
                        {"tool_call_id": "c1", "name": "search", "arguments": {"q": "x"}}
                    ],
                ),
            ]
        ],
        on_tool_results={
            0: [
                NormalizedEvent(type=EventType.TEXT_DELTA, text="found it"),
                NormalizedEvent(type=EventType.DONE),
            ]
        },
    )
    transport = EchoTransport(script)

    before = [e async for e in transport.send_user_message("search x")]
    assert before[-1].type is EventType.TOOL_CALLS

    after = [
        e
        async for e in transport.send_tool_results(
            [ToolResult(tool_call_id="c1", result={"r": 1})]
        )
    ]
    assert after[-1].type is EventType.DONE
    assert after[0].text == "found it"
