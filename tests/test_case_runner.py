"""CaseRunner：验证消费 EchoTransport 的事件流并累积 round_data。"""
from __future__ import annotations

from agentrig.case_runner import CaseRunner
from agentrig.transports.base import EventType, NormalizedEvent
from agentrig.transports.echo import EchoScript, EchoTransport


async def test_minimal_case() -> None:
    script = EchoScript(
        on_user_message=[
            [
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
                NormalizedEvent(type=EventType.TEXT_DELTA, text="done"),
                NormalizedEvent(type=EventType.DONE),
            ]
        },
    )
    runner = CaseRunner(EchoTransport(script))
    rounds = [r async for r in runner.run("search x")]

    assert len(rounds) == 1
    rd = rounds[0]
    assert rd.done is True
    assert rd.assistant_text == "done"
    assert len(rd.tool_calls) == 1
    assert rd.tool_calls[0].name == "search"
    assert len(rd.tool_results) == 1
