"""execution 组 MCP 工具：跑测试用例。

run_single_case 从 repo 取 case，构造 transport + mock，CaseRunner 跑，
返回结果（passed + tool_calls + missing expected + error）。

transport 双模式：配了 AGENTRIG_AGENT__SERVER_URL 走 StreamingChatTransport
（真实被测 agent）；否则降级 EchoTransport（模拟 agent 按 case.mock 自呼自应，
供无 agent 环境冒烟/单测）。
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..case_runner import CaseRunner
from ..config import get_settings
from ..judges import rule_judge
from ..mock import ToolMockHub
from ..models import TestCase
from ..storage import TestCaseRepo, get_repo
from ..transports.base import EventType, NormalizedEvent
from ..transports.echo import EchoScript, EchoTransport
from ..transports.streaming_chat import StreamingChatTransport


def _build_real_transport() -> StreamingChatTransport | None:
    """配了 agent server_url 则返回真实 transport，否则 None（降级 echo）。"""
    url = get_settings().agent.server_url
    if not url:
        return None
    return StreamingChatTransport(url)


def _echo_script_for_case(case: TestCase) -> EchoScript:
    """降级模式：echo 按 case.mock / expected_tools 自呼自应。"""
    tools_to_call = list(case.mock.keys()) or list(case.expected_tools)
    if tools_to_call:
        on_user_message = [
            [
                NormalizedEvent(
                    type=EventType.TOOL_CALLS,
                    tool_calls=[
                        {"tool_call_id": f"tc{i}", "name": t, "arguments": {}}
                        for i, t in enumerate(tools_to_call)
                    ],
                )
            ]
        ]
        on_tool_results = {
            i: [NormalizedEvent(type=EventType.DONE)] for i in range(len(tools_to_call))
        }
    else:
        on_user_message = [
            [
                NormalizedEvent(type=EventType.TEXT_DELTA, text="(no tools)"),
                NormalizedEvent(type=EventType.DONE),
            ]
        ]
        on_tool_results = {}
    return EchoScript(on_user_message=on_user_message, on_tool_results=on_tool_results)


async def run_single_case_impl(
    repo: TestCaseRepo, case_id: str
) -> dict[str, Any]:
    """跑一个用例，返回结果 dict。

    - transport：有 agent url 走真实，否则降级 echo
    - mock：case.mock 作 ToolMockHub 的 L0 inline
    - 断言：expected_tools 都被调了 + 无 error → passed
    """
    case = repo.get(case_id)
    if case is None:
        return {"error": f"not found: {case_id}"}

    hub = ToolMockHub()
    for tool, result in case.mock.items():
        hub.set_inline(tool, result)

    real_transport = _build_real_transport()
    transport: StreamingChatTransport | EchoTransport = (
        real_transport
        if real_transport is not None
        else EchoTransport(_echo_script_for_case(case))
    )

    runner = CaseRunner(transport, mock_policy=hub)
    rounds = [r async for r in runner.run(case.user_message)]
    if not rounds:
        return {"error": "no round produced", "case_id": case.id}
    rd = rounds[-1]

    called = {tc.name for tc in rd.tool_calls}
    missing = set(case.expected_tools) - called

    verdict = rule_judge.judge(rd, case)

    return {
        "case_id": case.id,
        "passed": verdict.passed,
        "reasons": verdict.reasons,
        "assistant_text": rd.assistant_text,
        "tool_calls": [tc.name for tc in rd.tool_calls],
        "tool_results_count": len(rd.tool_results),
        "missing_expected_tools": sorted(missing),
        "error": rd.error,
        "transport": "real" if real_transport is not None else "echo",
    }


def register(mcp: FastMCP) -> None:
    """注册 execution 工具到 FastMCP。"""

    @mcp.tool()
    async def run_single_case(case_id: str) -> str:
        """跑一个测试用例，返回结果（passed/tool_calls/missing_expected/error）。"""
        result = await run_single_case_impl(get_repo(), case_id)
        return json.dumps(result, ensure_ascii=False, default=str)
