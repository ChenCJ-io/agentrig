"""测试执行的领域模型（协议无关）。"""
from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, field_validator


class ToolCall(BaseModel):
    """agent 的一次工具调用。"""

    tool_call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具调用的返回结果（mock 或真实）。"""

    tool_call_id: str
    # 工具名：streaming-chat tool_result item 必填；OpenAI tool message 不要但携带无害
    name: str
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

    最小字段集：输入 + 期望工具 + mock 配置 + 标签 + 断言/判据。
    后续 PR 加 scenario（多轮）。
    """

    # pytest 默认收集 Test* 类当测试；这是领域模型，标记不收集
    __test__: ClassVar[bool] = False

    id: str
    name: str
    user_message: str
    # 期望 agent 调用的工具名（断言用；空则不断言；等价于 expectations 的一种糖）
    expected_tools: list[str] = Field(default_factory=list)
    # 结构化断言：[{kind, ...}]，kind ∈
    # expected_tools / text_contains / tool_call_order / not_called
    expectations: list[dict[str, Any]] = Field(default_factory=list)
    # 工具名 -> mock 结果（L0 风格，简化；后续接 ToolMockHub 完整配置）
    mock: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    # ai judge 的自然语言判据（judge_mode="ai" 时用）
    rubric: str | None = None
    # 判定模式：rule（结构化断言）/ ai（LLM 按 rubric）/ off（只判 error）
    judge_mode: Literal["rule", "ai", "off"] = "rule"

    @field_validator("expectations")
    @classmethod
    def _validate_expectations(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        known = {"expected_tools", "text_contains", "tool_call_order", "not_called"}
        for e in v:
            if e.get("kind") not in known:
                raise ValueError(
                    f"unknown expectation kind: {e.get('kind')!r}（允许：{sorted(known)}）"
                )
        return v
