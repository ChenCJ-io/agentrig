"""AgentTransport Protocol + NormalizedEvent 中间表示。

transport 抽象掉被测 agent 的协议。它只负责一件事：驱动 agent 一段
（一条用户消息或一次 tool_result 回灌），把 agent 接下来产出的内容归一成
`NormalizedEvent`。

递归 tool-calling 回路拆给调用方（CaseRunner）：transport yield 出
TOOL_CALLS 时，CaseRunner 生成 mock 并调 `send_tool_results` 继续。
这是对「把 mock 焊死在 transport 内」的写法的刻意反转 —— 那种写法难测试、
难换 mock 策略；这里把 mock 注入交给调用方（CaseRunner）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..models import ToolResult


class EventType(str, Enum):
    """归一事件类型，覆盖老 SSE 协议及扩展。"""

    SESSION_CREATED = "session_created"
    TEXT_DELTA = "text_delta"
    TOOL_CALLS = "tool_calls"
    TOOL_RESULTS = "tool_results"
    TODOS = "todos"
    DONE = "done"
    ERROR = "error"


class NormalizedEvent(BaseModel):
    """协议无关的事件，由 transport 产出。"""

    type: EventType
    session_id: str | None = None
    text: str | None = None  # TEXT_DELTA 用
    # TOOL_CALLS: [{tool_call_id, name, arguments}]
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    # TOOL_RESULTS（仅当 transport 回放自己的回灌时用）
    tool_results: list[ToolResult] = Field(default_factory=list)
    todos: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    raw: dict[str, Any] | None = None  # 原始 payload，诊断用


@runtime_checkable
class AgentTransport(Protocol):
    """被测 agent 的抽象通信层。

    方法声明为普通函数返回 `AsyncIterator` —— 实现用 `async def` + `yield`
    （async generator）。调用方**不需要** await 方法本身，直接对返回的
    迭代器 `async for` 即可。
    """

    def send_user_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[NormalizedEvent]: ...

    def send_tool_results(
        self,
        results: list[ToolResult],
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[NormalizedEvent]: ...
