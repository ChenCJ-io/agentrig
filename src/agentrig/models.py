"""测试执行的领域模型（协议无关）。"""
from __future__ import annotations

from typing import Any, ClassVar

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


class TestCase(BaseModel):
    """一个测试用例（CC 通过 authoring MCP 工具构建）。

    第一周最小字段集：输入 + 期望工具 + mock 配置 + 标签。
    后续 PR 加 scenario（多轮）/ rubric（断言语义）/ judge_mode。
    """

    # pytest 默认收集 Test* 类当测试；这是领域模型，标记不收集
    __test__: ClassVar[bool] = False

    id: str
    name: str
    user_message: str
    # 期望 agent 调用的工具名（断言用；空则不断言）
    expected_tools: list[str] = Field(default_factory=list)
    # 工具名 -> mock 结果（L0 风格，第一周简化；后续接 ToolMockHub 完整配置）
    mock: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
