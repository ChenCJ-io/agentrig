"""CaseRunner：transport 与机判之间的胶水层。

持有递归 tool-calling 循环：消费 transport 的 NormalizedEvent 流；
遇 TOOL_CALLS 时，生成 mock 并通过 send_tool_results 回灌；
全部累积进 `RoundData`。

单场景单轮编排（无机判）。mock 生成通过 mock_policy 注入（ToolMockHub 实现
MockPolicy）；不传则用占位（echo 工具名）。递归深度受 max_rounds 限制。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .models import RoundData, ToolCall, ToolResult
from .proxy.mock_policy import MockPolicy
from .transports.base import AgentTransport, EventType, NormalizedEvent


class CaseRunner:
    """单场景编排器（一轮，无机判）。"""

    def __init__(
        self,
        transport: AgentTransport,
        *,
        mock_policy: MockPolicy | None = None,
        max_rounds: int = 10,
    ) -> None:
        self.transport = transport
        self.mock_policy = mock_policy
        self.max_rounds = max_rounds

    async def run(
        self, user_message: str, session_id: str | None = None
    ) -> AsyncIterator[RoundData]:
        rd = RoundData(round_number=0, user_message=user_message, session_id=session_id)
        await self._drive(
            self.transport.send_user_message(user_message, session_id=session_id), rd
        )
        yield rd

    async def _drive(
        self,
        events: AsyncIterator[NormalizedEvent],
        rd: RoundData,
        *,
        depth: int = 0,
    ) -> None:
        """消费一段事件流；遇 TOOL_CALLS 时，生成 mock 并递归继续。

        depth 限制 tool-calling 递归深度，超过 max_rounds 则记 error 停止
        （防止 agent 陷入 tool-call 死循环导致无限递归）。
        """
        async for ev in events:
            if ev.type is EventType.SESSION_CREATED and ev.session_id:
                rd.session_id = ev.session_id
            elif ev.type is EventType.TEXT_DELTA and ev.text:
                rd.assistant_text += ev.text
            elif ev.type is EventType.TOOL_CALLS:
                rd.tool_calls.extend(ToolCall(**tc) for tc in ev.tool_calls)
                results = await self._generate_mocks(rd.tool_calls)
                rd.tool_results.extend(results)
                if depth + 1 >= self.max_rounds:
                    rd.error = f"max_rounds exceeded ({self.max_rounds})"
                    return
                await self._drive(
                    self.transport.send_tool_results(results, session_id=rd.session_id),
                    rd,
                    depth=depth + 1,
                )
            elif ev.type is EventType.DONE:
                rd.done = True
            elif ev.type is EventType.ERROR:
                rd.error = ev.error

    async def _generate_mocks(self, calls: list[ToolCall]) -> list[ToolResult]:
        """生成 mock：mock_policy 命中用预设，否则占位（防未配 mock 的工具调用报错）。"""
        results: list[ToolResult] = []
        for c in calls:
            if self.mock_policy is not None and self.mock_policy.should_mock(
                c.name, c.arguments
            ):
                result: Any = self.mock_policy.generate(c.name, c.arguments)
            else:
                result = {"echo": c.name}
            results.append(
                ToolResult(tool_call_id=c.tool_call_id, name=c.name, result=result)
            )
        return results
