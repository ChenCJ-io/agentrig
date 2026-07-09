"""端到端测试：StreamingChatTransport 连 demo_agent，验证真实 tool-call 闭环。

形态1（execution 驱动 agent）：demo_agent 产出 tool_calls → CaseRunner 用 hub
mock 回灌 → agent 收 tool_result 后 done。不经 EchoTransport、不凭空自呼自应。
"""
from __future__ import annotations

from asgi_lifespan import LifespanManager
from httpx import ASGITransport

from agentrig.case_runner import CaseRunner
from agentrig.mock import ToolMockHub
from agentrig.transports.streaming_chat import StreamingChatTransport


async def test_real_transport_tool_call_loop_against_demo_agent() -> None:
    """含 'echo' 关键词 → demo_agent 调 echo → hub mock 回灌 → done。"""
    from examples.demo_agent import app as demo_app

    async with LifespanManager(demo_app):
        transport = StreamingChatTransport(
            base_url="http://test",
            transport=ASGITransport(app=demo_app),
        )
        hub = ToolMockHub()
        hub.set_inline("echo", {"reply": "mocked-echo"})
        runner = CaseRunner(transport, mock_policy=hub, max_rounds=5)

        rounds = [r async for r in runner.run("please echo this")]
        assert len(rounds) == 1
        rd = rounds[0]

        assert rd.error is None
        assert rd.done is True
        assert [tc.name for tc in rd.tool_calls] == ["echo"]
        assert rd.tool_results[0].result == {"reply": "mocked-echo"}
        assert "ok" in rd.assistant_text  # demo_agent 回灌后 text_delta "ok"


async def test_real_transport_text_only_path() -> None:
    """无工具关键词 → demo_agent 直接 text+done（不走 tool_call 回路）。"""
    from examples.demo_agent import app as demo_app

    async with LifespanManager(demo_app):
        transport = StreamingChatTransport(
            base_url="http://test",
            transport=ASGITransport(app=demo_app),
        )
        runner = CaseRunner(transport, max_rounds=5)
        rounds = [r async for r in runner.run("just chat")]
        rd = rounds[0]
        assert rd.error is None
        assert rd.done is True
        assert rd.tool_calls == []
        assert "just chat" in rd.assistant_text


async def test_real_transport_unmocked_tool_uses_placeholder() -> None:
    """agent 调了未配 mock 的工具 → CaseRunner 用占位 result 继续（不崩溃）。"""
    from examples.demo_agent import app as demo_app

    async with LifespanManager(demo_app):
        transport = StreamingChatTransport(
            base_url="http://test",
            transport=ASGITransport(app=demo_app),
        )
        hub = ToolMockHub()  # 不设任何 inline
        runner = CaseRunner(transport, mock_policy=hub, max_rounds=5)

        rounds = [r async for r in runner.run("please reverse this")]
        rd = rounds[0]
        assert rd.error is None
        assert [tc.name for tc in rd.tool_calls] == ["reverse"]
        # 未 mock → 占位 {"echo": "reverse"}
        assert rd.tool_results[0].result == {"echo": "reverse"}
