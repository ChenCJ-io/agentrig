"""sampling 工具 get_real_tool_samples 测试。"""
from __future__ import annotations

from mcp import types

from agentrig.mcp_tools.sampling import get_real_tool_samples_impl
from agentrig.proxy.trace import TraceEntry
from agentrig.runtime import get_runtime, reset_runtime


def test_samples_default_real_only() -> None:
    """默认只取 source=real 的样本，并从 ContentBlock 提取 text。"""
    reset_runtime()
    rt = get_runtime()
    rt.trace.entries = [
        TraceEntry(
            "echo__echo", {"text": "a"}, source="real",
            result=[types.TextContent(type="text", text="ra")],
        ),
        TraceEntry("echo__echo", {"text": "b"}, source="mock", result="mocked"),
        TraceEntry(
            "echo__reverse", {}, source="real",
            result=[types.TextContent(type="text", text="r1")],
        ),
    ]
    samples = get_real_tool_samples_impl()
    assert len(samples) == 2
    assert all(s["source"] == "real" for s in samples)
    assert samples[0]["result"] == ["ra"]
    assert samples[1]["result"] == ["r1"]
    reset_runtime()


def test_samples_filter_by_tool_name() -> None:
    """tool_name 过滤只返回匹配工具。"""
    reset_runtime()
    rt = get_runtime()
    rt.trace.entries = [
        TraceEntry(
            "echo__echo", {}, source="real",
            result=[types.TextContent(type="text", text="x")],
        ),
        TraceEntry(
            "echo__reverse", {}, source="real",
            result=[types.TextContent(type="text", text="y")],
        ),
    ]
    samples = get_real_tool_samples_impl("echo__reverse")
    assert len(samples) == 1
    assert samples[0]["tool_name"] == "echo__reverse"
    assert samples[0]["result"] == ["y"]
    reset_runtime()


def test_samples_include_mock_when_source_none() -> None:
    """source=None 取全部（含 mock），mock result 原样返回。"""
    reset_runtime()
    rt = get_runtime()
    rt.trace.entries = [
        TraceEntry(
            "t", {}, source="real",
            result=[types.TextContent(type="text", text="r")],
        ),
        TraceEntry("t", {}, source="mock", result={"k": "v"}),
    ]
    samples = get_real_tool_samples_impl(source=None)
    assert len(samples) == 2
    sources = {s["source"] for s in samples}
    assert sources == {"real", "mock"}
    reset_runtime()


def test_samples_empty_trace() -> None:
    """空 trace 返回空列表。"""
    reset_runtime()
    get_runtime()  # 建空 runtime
    assert get_real_tool_samples_impl() == []
    reset_runtime()
