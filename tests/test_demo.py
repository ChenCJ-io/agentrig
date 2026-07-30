"""agentrig demo 一键验收命令测试。"""
from __future__ import annotations

from agentrig.demo import run_demo


async def test_run_demo_returns_zero_when_passing() -> None:
    """验收演示应跑通内置的 search→summarize 闭环并返回 0。"""
    code = await run_demo()
    assert code == 0
