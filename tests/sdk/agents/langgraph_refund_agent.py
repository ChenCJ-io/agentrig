"""LangGraph 版退款 Agent：create_agent + 脚本化假模型，逻辑与 Agno 版一致。"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from refund_script import REAL_TOOL_MARKER, refund_steps, reply


@tool
def lookup_order(order_id: str) -> dict[str, Any]:
    """Look up an order by id and return its status and amount."""

    return {"order_id": order_id, "amount": 199, "note": REAL_TOOL_MARKER}


@tool
def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order. This has an external side effect."""

    return f"{REAL_TOOL_MARKER}: refunded {order_id} ({amount})"


class ScriptedChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._respond(messages))])

    def _respond(self, messages: list[BaseMessage]) -> AIMessage:
        metadata: dict[str, Any] = {
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "response_metadata": {"model_name": "scripted-model"},
        }
        last_user = max(
            index for index, message in enumerate(messages) if isinstance(message, HumanMessage)
        )
        results = [
            message for message in messages[last_user + 1 :] if isinstance(message, ToolMessage)
        ]
        steps = refund_steps(str(messages[last_user].content))
        if len(results) < len(steps):
            name, arguments = steps[len(results)]
            return AIMessage(
                content="",
                tool_calls=[{"id": f"call_{len(messages)}", "name": name, "args": arguments}],
                **metadata,
            )
        last = str(results[-1].content) if results else ""
        return AIMessage(content=reply(steps, last), **metadata)


agent = create_agent(
    ScriptedChatModel(),
    tools=[lookup_order, issue_refund],
    system_prompt="You are a refund assistant.",
)
