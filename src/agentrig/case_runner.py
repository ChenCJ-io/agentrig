"""CaseRunner：transport 与机判之间的胶水层。

持有递归 tool-calling 循环：消费 transport 的 NormalizedEvent 流；
遇 TOOL_CALLS 时，生成 mock 并通过 send_tool_results 回灌；
全部累积进 `RoundData`。

第一周范围：单场景单轮，不做机判。`_generate_mocks` 是占位；
后续 PR 接 ToolMockHub（L0/L1/L2）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from .models import RoundData, ToolCall, ToolResult
from .transports.base import AgentTransport, EventType, NormalizedEvent


class CaseRunner:
    """单场景编排器（第一周：一轮，无机判）。"""

    def __init__(self, transport: AgentTransport, *, max_rounds: int = 10) -> None:
        self.transport = transport
        self.max_rounds = max_rounds

    async def run(
        self, user_message: str, session_id: str | None = None
    ) -> AsyncIterator[RoundData]:
        rd = RoundData(round_number=0, user_message=user_message, session_id=session_id)
        await self._drive(
            self.transport.send_user_message(user_message, session_id=session_id), rd
        )
        yield rd

    async def _drive(self, events: AsyncIterator[NormalizedEvent], rd: RoundData) -> None:
        """消费一段事件流；遇 TOOL_CALLS 时，生成 mock 并递归继续。"""
        async for ev in events:
            if ev.type is EventType.SESSION_CREATED and ev.session_id:
                rd.session_id = ev.session_id
            elif ev.type is EventType.TEXT_DELTA and ev.text:
                rd.assistant_text += ev.text
            elif ev.type is EventType.TOOL_CALLS:
                rd.tool_calls.extend(ToolCall(**tc) for tc in ev.tool_calls)
                results = await self._generate_mocks(rd.tool_calls)
                rd.tool_results.extend(results)
                await self._drive(
                    self.transport.send_tool_results(results, session_id=rd.session_id),
                    rd,
                )
            elif ev.type is EventType.DONE:
                rd.done = True
            elif ev.type is EventType.ERROR:
                rd.error = ev.error

    async def _generate_mocks(self, calls: list[ToolCall]) -> list[ToolResult]:
        """占位 mock 策略；后续 PR 接 ToolMockHub。"""
        return [
            ToolResult(tool_call_id=c.tool_call_id, result={"echo": c.name}) for c in calls
        ]
