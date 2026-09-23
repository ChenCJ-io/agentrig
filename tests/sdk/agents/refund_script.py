"""两个框架版退款 Agent 共用的脚本：候选版本跳过用户确认，直接调用有副作用的退款工具。"""

from __future__ import annotations

from typing import Any

from agentrig.sdk import current

REAL_TOOL_MARKER = "REAL-TOOL-RAN"


def refund_steps(user_text: str) -> list[tuple[str, dict[str, Any]]]:
    if user_text == "确认":
        return [("issue_refund", {"order_id": "A123", "amount": 199})]
    steps: list[tuple[str, dict[str, Any]]] = [("lookup_order", {"order_id": "A123"})]
    context = current()
    if context is not None and context.version == "candidate-regression":
        steps.append(("issue_refund", {"order_id": "A123", "amount": 199}))
    return steps


def reply(steps: list[tuple[str, dict[str, Any]]], last_result: str) -> str:
    if steps[-1][0] == "issue_refund":
        return f"已退款：{last_result}"
    return f"订单信息：{last_result}，请确认是否退款"
