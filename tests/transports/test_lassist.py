"""LassistTransport 单元测试：SSE 解析 + 事件归一 + tool_result item 构造。

httpx 部分需真实 Lassist agent，留集成测试；这里测纯函数。
"""
from __future__ import annotations

from agentrig.models import ToolResult
from agentrig.transports.base import EventType
from agentrig.transports.lassist import _build_tool_result_item, _parse_sse_line


def test_parse_session_created() -> None:
    line = 'data: {"type":"session_created","run_id":"r1","data":{"session_id":"s1"}}'
    ev = _parse_sse_line(line)
    assert ev is not None
    assert ev.type is EventType.SESSION_CREATED
    assert ev.session_id == "s1"


def test_parse_text_delta() -> None:
    line = 'data: {"type":"text_delta","run_id":"r1","data":{"index":0,"text":"你好"}}'
    ev = _parse_sse_line(line)
    assert ev is not None
    assert ev.type is EventType.TEXT_DELTA
    assert ev.text == "你好"


def test_parse_tool_calls_normalizes_id_and_input() -> None:
    """id → tool_call_id, input → arguments, 丢弃 type。"""
    line = (
        'data: {"type":"tool_calls","run_id":"r1","data":{"tool_calls":'
        '[{"id":"tc1","type":"function","name":"read","input":{"path":"/x"}}]}}'
    )
    ev = _parse_sse_line(line)
    assert ev is not None
    assert ev.type is EventType.TOOL_CALLS
    assert ev.tool_calls == [
        {"tool_call_id": "tc1", "name": "read", "arguments": {"path": "/x"}}
    ]


def test_parse_done() -> None:
    ev = _parse_sse_line('data: {"type":"done","run_id":"r1","data":{"result":"completed"}}')
    assert ev is not None
    assert ev.type is EventType.DONE


def test_parse_error() -> None:
    ev = _parse_sse_line('data: {"type":"error","run_id":"r1","data":{"message":"boom"}}')
    assert ev is not None
    assert ev.type is EventType.ERROR
    assert ev.error == "boom"


def test_parse_non_data_line_returns_none() -> None:
    assert _parse_sse_line("") is None
    assert _parse_sse_line("event: ping") is None  # Lassist 不用 event: 行
    assert _parse_sse_line("data: not-json") is None
    assert _parse_sse_line("data: ") is None


def test_parse_unknown_type_returns_none() -> None:
    """suggestions/questions 等第一周不归一，返回 None（后续 PR 扩展）。"""
    ev = _parse_sse_line('data: {"type":"suggestions","data":{"items":["x"]}}')
    assert ev is None


def test_build_tool_result_item_serializes_result_as_json_string() -> None:
    """result 必须是 JSON 字符串（Lassist 协议），不是对象。"""
    item = _build_tool_result_item(
        ToolResult(tool_call_id="tc1", name="read", result={"k": "v"})
    )
    assert item["tool_call_id"] == "tc1"
    assert item["name"] == "read"
    assert item["result"] == '{"k": "v"}'  # JSON 字符串
    assert item["status"] == "success"


def test_build_tool_result_item_passes_string_result_through() -> None:
    """result 已是字符串时直接用（不再二次序列化）。"""
    item = _build_tool_result_item(
        ToolResult(tool_call_id="tc1", name="read", result="raw-string")
    )
    assert item["result"] == "raw-string"
