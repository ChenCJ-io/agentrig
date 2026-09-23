"""Agno 版退款 Agent 与 Team：脚本化假模型按 AgentRig 版本决定是否跳过用户确认。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.team import Team
from refund_script import REAL_TOOL_MARKER, refund_steps, reply


def lookup_order(order_id: str) -> str:
    """Look up an order by id and return its status and amount."""

    return json.dumps({"order_id": order_id, "amount": 199, "note": REAL_TOOL_MARKER})


def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order. This has an external side effect."""

    return f"{REAL_TOOL_MARKER}: refunded {order_id} ({amount})"


@dataclass
class ScriptedModel(Model):
    id: str = "scripted-model"
    name: str = "ScriptedModel"
    provider: str = "scripted"
    leader: bool = False

    def _respond(self, messages: list[Any]) -> ModelResponse:
        usage = MessageMetrics(input_tokens=10, output_tokens=5, total_tokens=15)
        last_user = max(
            index for index, message in enumerate(messages) if message.role == "user"
        )
        results = [message for message in messages[last_user + 1 :] if message.role == "tool"]
        user_text = str(messages[last_user].content)
        steps = (
            [("delegate_task_to_member", {"member_id": "refund-agent", "task": user_text})]
            if self.leader
            else refund_steps(user_text)
        )
        if len(results) < len(steps):
            name, arguments = steps[len(results)]
            return ModelResponse(
                role="assistant",
                response_usage=usage,
                tool_calls=[
                    {
                        "id": f"call_{len(messages)}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            )
        last = str(results[-1].content) if results else ""
        text = f"团队回复：{last}" if self.leader else reply(steps, last)
        return ModelResponse(role="assistant", content=text, response_usage=usage)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._respond(kwargs["messages"])

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._respond(kwargs["messages"])

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._respond(kwargs["messages"])

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._respond(kwargs["messages"])

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> Any:
        return response

    def _parse_provider_response_delta(self, response: Any) -> Any:
        return response


agent = Agent(
    id="refund-agent",
    name="Refund Agent",
    model=ScriptedModel(),
    tools=[lookup_order, issue_refund],
    telemetry=False,
)

team = Team(
    id="support-team",
    name="Support Team",
    model=ScriptedModel(leader=True),
    members=[agent],
    telemetry=False,
)
