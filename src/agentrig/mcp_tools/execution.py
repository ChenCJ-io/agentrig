"""execution 组 MCP 工具：跑测试用例。

run_single_case 从 repo 取 case，构造 transport + mock，CaseRunner 跑，
返回结果（passed + tool_calls + missing expected + error）。

第一周 transport 用 EchoTransport（模拟 agent 调 case.mock 的工具）；
后续 PR 接真实 transport（Lassist/OpenAI/MCP）。
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..case_runner import CaseRunner
from ..mock import ToolMockHub
from ..storage import get_repo
from ..storage.repo import InMemoryTestCaseRepo
from ..transports.base import EventType, NormalizedEvent
from ..transports.echo import EchoScript, EchoTransport


async def run_single_case_impl(
    repo: InMemoryTestCaseRepo, case_id: str
) -> dict[str, Any]:
    """跑一个用例，返回结果 dict。

    - agent 要调的工具：优先 case.mock 的 key（mock 啥调啥），否则 expected_tools
    - mock：case.mock 作 ToolMockHub 的 L0 inline
    - 断言：expected_tools 都被调了 + 无 error → passed
    """
    case = repo.get(case_id)
    if case is None:
        return {"error": f"not found: {case_id}"}

    # agent 要调的工具（EchoTransport 剧本依据）
    tools_to_call = list(case.mock.keys()) or list(case.expected_tools)

    # 构造 EchoTransport 剧本：agent 调这些工具，回灌后 done
    on_tool_results: dict[int, list[NormalizedEvent]] = {}
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

    transport = EchoTransport(
        EchoScript(on_user_message=on_user_message, on_tool_results=on_tool_results)
    )

    # mock_policy: case.mock 作 L0 inline
    hub = ToolMockHub()
    for tool, result in case.mock.items():
        hub.set_inline(tool, result)

    runner = CaseRunner(transport, mock_policy=hub)
    rounds = [r async for r in runner.run(case.user_message)]
    if not rounds:
        return {"error": "no round produced", "case_id": case.id}
    rd = rounds[-1]

    called = {tc.name for tc in rd.tool_calls}
    missing = set(case.expected_tools) - called
    passed = not missing and rd.error is None

    return {
        "case_id": case.id,
        "passed": passed,
        "assistant_text": rd.assistant_text,
        "tool_calls": [tc.name for tc in rd.tool_calls],
        "tool_results_count": len(rd.tool_results),
        "missing_expected_tools": sorted(missing),
        "error": rd.error,
    }


def register(mcp: FastMCP) -> None:
    """注册 execution 工具到 FastMCP。"""

    @mcp.tool()
    async def run_single_case(case_id: str) -> str:
        """跑一个测试用例，返回结果（passed/tool_calls/missing_expected/error）。"""
        result = await run_single_case_impl(get_repo(), case_id)
        return json.dumps(result, ensure_ascii=False, default=str)
