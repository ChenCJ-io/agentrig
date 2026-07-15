"""agentrig demo：一键自检验收。

起内进程 sample_agent（search → summarize 两步 tool-calling），跑一条多步用例，
打印人类可读的验收报告，证明平台核心闭环（真实 transport + mock 注入 + 多轮
tool-calling + 机判）工作。退出码 0=通过。

    uv run agentrig demo
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from httpx import ASGITransport

from .case_runner import CaseRunner
from .judges import rule_judge
from .mock import ToolMockHub
from .models import TestCase
from .transports.streaming_chat import StreamingChatTransport


def _load_sample_app() -> Any:
    """从 examples/ 加载 sample_agent 的 FastAPI app（examples 不在安装包内）。"""
    repo_root = Path(__file__).resolve().parents[2]  # src/agentrig/demo.py → 仓库根
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    mod = importlib.import_module("examples.sample_agent")
    return mod.app


async def run_demo() -> int:
    """跑验收演示，返回退出码（0=通过，1=失败）。"""
    from asgi_lifespan import LifespanManager

    sample_app = _load_sample_app()

    case = TestCase(
        id="acceptance-search-summarize",
        name="搜索后总结（验收用例）",
        user_message="帮我查一下 AgentRig 并总结",
        expected_tools=["search", "summarize"],
        expectations=[{"kind": "tool_call_order", "tools": ["search", "summarize"]}],
        mock={
            "search": {"hits": [{"title": "AgentRig", "url": "https://example.com"}], "total": 1},
            "summarize": "AgentRig 是 MCP 原生 agent 测试台。",
        },
        tags=["acceptance"],
    )

    transport = StreamingChatTransport(
        base_url="http://test", transport=ASGITransport(app=sample_app)
    )
    hub = ToolMockHub()
    for tool, result in case.mock.items():
        hub.set_inline(tool, result)

    async with LifespanManager(sample_app):
        runner = CaseRunner(transport, mock_policy=hub, max_rounds=10)
        rounds = [r async for r in runner.run(case.user_message)]

    rd = rounds[-1]
    verdict = rule_judge.judge(rd, case)

    print("=" * 60)
    print("AgentRig 验收演示（真实 transport + mock + 多轮 tool-calling + 机判）")
    print("=" * 60)
    print(f"用例      : {case.name}")
    print(f"输入      : {case.user_message}")
    print(f"工具调用  : {[tc.name for tc in rd.tool_calls]}")
    print(f"mock 回灌 : {len(rd.tool_results)} 次")
    print(f"agent 回复: {rd.assistant_text or '(无)'}")
    print(f"执行错误  : {rd.error or '无'}")
    print("-" * 60)
    print(f"判定      : {'✅ PASS' if verdict.passed else '❌ FAIL'}")
    for reason in verdict.reasons:
        print(f"  - {reason}")
    print("=" * 60)
    return 0 if verdict.passed else 1
