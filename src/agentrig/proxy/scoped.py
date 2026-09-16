"""CaseRun 级 MCP Proxy 作用域。

Proxy 模式下，被测 Agent 自己通过 MCP 调工具。这个模块把一次 MCP 工具调用
重新接回该 CaseRun 独享的 Provider 链，并将证据写入与 controlled 模式相同的
事件流。作用域用随机令牌寻址，运行结束立即撤销。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..identifiers import new_id
from ..runs.event_recorder import EventRecorder
from ..runs.models import RunEventType
from ..runs.repository import RunRepository
from ..runs.schemas import CaseRunDetail
from ..targets.drivers import ToolCall, ToolResult
from ..tool_results.chain import ProviderChain, ProviderExhausted
from ..tool_results.providers import ProviderAttempt, ProviderContext


@dataclass
class ProxyScope:
    token: str
    detail: CaseRunDetail
    chain: ProviderChain
    runs: RunRepository
    recorder: EventRecorder
    turn_position: int = 0
    simulation_state: dict[str, Any] = field(default_factory=dict)
    tool_call_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def select_turn(self, position: int) -> None:
        self.turn_position = position

    def all_fixtures(self) -> list[dict[str, Any]]:
        """返回整条用例的 Fixture，供会话建立时生成工具目录。"""

        return [
            dict(fixture)
            for turn in self.detail.case_snapshot["turns"]
            for fixture in turn.get("fixtures", [])
        ]

    def declared_tools(self) -> list[dict[str, Any]]:
        """返回 Target 声明的 MCP-native 工具目录。"""

        value = dict(self.detail.target_snapshot.get("options") or {}).get(
            "tool_catalog",
            [],
        )
        if not isinstance(value, list):
            raise RuntimeError("target options.tool_catalog must be a list")
        if not all(isinstance(item, dict) for item in value):
            raise RuntimeError("target options.tool_catalog items must be objects")
        return [dict(item) for item in value]

    def current_fixture(self, tool_name: str) -> dict[str, Any] | None:
        """返回当前轮第一个同名 Fixture，用于推导工具结果 Schema。"""

        return next(
            (
                dict(fixture)
                for fixture in self._turn().get("fixtures", [])
                if fixture.get("tool_name") == tool_name
            ),
            None,
        )

    async def resolve(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        result_schema: dict[str, Any] | None,
    ) -> ToolResult:
        # Provider 内有一次性 Fixture、序列 Sample 和模拟状态。串行化可保证
        # 即使被测 Agent 并发发起 MCP 调用，消费顺序仍是确定的。
        async with self._lock:
            return await self._resolve_locked(
                tool_name,
                arguments,
                result_schema=result_schema,
            )

    async def _resolve_locked(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        result_schema: dict[str, Any] | None,
    ) -> ToolResult:
        turn = self._turn()
        call = ToolCall(
            id=new_id("toolcall"),
            name=tool_name,
            arguments=arguments,
            result_schema=result_schema,
        )
        call_event = await self.recorder.record(
            self.detail.id,
            RunEventType.TOOL_CALL,
            {
                "turn_position": self.turn_position,
                "tool_call_id": call.id,
                "tool_name": call.name,
                "arguments": call.arguments,
                "result_schema": call.result_schema,
                "via": "mcp_proxy",
            },
        )
        self.tool_call_count += 1
        if self.tool_call_count > 50:
            raise RuntimeError("case run exceeded 50 tool calls")
        latest = await self.runs.get_case_run(self.detail.id)
        prior_events = latest.events if latest is not None else []
        context = ProviderContext(
            case_run_id=self.detail.id,
            turn_position=self.turn_position,
            tool_call=call,
            fixtures=turn.get("fixtures", []),
            version=self.detail.version,
            initial_state=dict(self.detail.case_snapshot.get("initial_state") or {}),
            simulation_instruction=turn.get("simulation_instruction"),
            prior_events=[item.model_dump(mode="json") for item in prior_events],
            simulation_state=self.simulation_state,
        )
        try:
            resolution = await self.chain.resolve(context)
        except ProviderExhausted as exc:
            await self._record_attempts(call, exc.attempts)
            if exc.validation_errors:
                await self.recorder.record(
                    self.detail.id,
                    RunEventType.VALIDATION,
                    {
                        "turn_position": self.turn_position,
                        "tool_call_id": call.id,
                        "valid": False,
                        "errors": exc.validation_errors,
                    },
                )
            raise
        await self._record_attempts(call, resolution.attempts)
        await self.recorder.record(
            self.detail.id,
            RunEventType.VALIDATION,
            {
                "turn_position": self.turn_position,
                "tool_call_id": call.id,
                "valid": True,
                "errors": [],
            },
        )
        result = resolution.result
        state_updates = result.metadata.get("state_updates")
        if isinstance(state_updates, dict):
            self.simulation_state.update(state_updates)
        await self.recorder.record(
            self.detail.id,
            RunEventType.TOOL_RESULT,
            {
                "turn_position": self.turn_position,
                "tool_call_id": call.id,
                "tool_call_event_id": call_event.id,
                "tool_name": call.name,
                "result": result.result,
                "source": result.source,
                "metadata": result.metadata,
                "via": "mcp_proxy",
            },
        )
        return result

    def _turn(self) -> dict[str, Any]:
        for turn in self.detail.case_snapshot["turns"]:
            if int(turn["position"]) == self.turn_position:
                return dict(turn)
        raise RuntimeError(
            f"proxy scope has no active turn at position {self.turn_position}"
        )

    async def _record_attempts(
        self,
        call: ToolCall,
        attempts: list[ProviderAttempt],
    ) -> None:
        for attempt in attempts:
            await self.recorder.record(
                self.detail.id,
                RunEventType.PROVIDER_ATTEMPT,
                {
                    "turn_position": self.turn_position,
                    "tool_call_id": call.id,
                    **attempt.model_dump(mode="json"),
                    "via": "mcp_proxy",
                },
            )


class ProxyScopeRegistry:
    """进程内短期作用域注册表；不承担跨进程会话共享。"""

    def __init__(self) -> None:
        self._scopes: dict[str, ProxyScope] = {}

    def register(
        self,
        detail: CaseRunDetail,
        chain: ProviderChain,
        *,
        runs: RunRepository,
        recorder: EventRecorder,
    ) -> ProxyScope:
        scope = ProxyScope(
            token=new_id("proxy"),
            detail=detail,
            chain=chain,
            runs=runs,
            recorder=recorder,
        )
        self._scopes[scope.token] = scope
        return scope

    def get(self, token: str) -> ProxyScope | None:
        return self._scopes.get(token)

    def revoke(self, token: str) -> None:
        self._scopes.pop(token, None)

    def active_count(self) -> int:
        return len(self._scopes)
