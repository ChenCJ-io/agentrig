"""测试执行的领域模型（协议无关）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """agent 的一次工具调用。"""

    tool_call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具调用的返回结果（mock 或真实）。"""

    tool_call_id: str
    # 当前先松散；后续 PR 约束为 MCP structured content。
    result: Any


class RoundData(BaseModel):
    """单轮对话的累积状态。

    由 CaseRunner 消费 transport 的 NormalizedEvent 流时填充。
    后续 PR 交给机判（rule/ai）消费。
    """

    round_number: int
    user_message: str
    session_id: str | None = None
    assistant_text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    todos: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    done: bool = False
