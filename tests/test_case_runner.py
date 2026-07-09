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


async def test_max_rounds_stops_infinite_tool_loop() -> None:
    """agent 陷入 tool-call 死循环时，max_rounds 截断并记 error（不无限递归）。"""
    loop_event = NormalizedEvent(
        type=EventType.TOOL_CALLS,
        tool_calls=[{"tool_call_id": "c", "name": "loop", "arguments": {}}],
    )
    script = EchoScript(
        on_user_message=[[loop_event]],
        on_tool_results={i: [loop_event] for i in range(10)},
    )
    runner = CaseRunner(EchoTransport(script), max_rounds=2)
    rounds = [r async for r in runner.run("loop")]

    rd = rounds[0]
    assert rd.error is not None
    assert "max_rounds" in rd.error
    assert rd.done is False
