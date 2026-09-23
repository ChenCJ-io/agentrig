"""harness 测试用的无框架退款 Agent：候选版本跳过用户确认直接退款。"""

from __future__ import annotations

import sys
from typing import Any

from agentrig.sdk import current, tool


@tool
def lookup_order(order_id: str) -> dict[str, Any]:
    """Look up an order by id."""

    return {"order_id": order_id, "status": "delivered", "amount": 199, "source": "real"}


@tool
def issue_refund(order_id: str, amount: float) -> str:
    """Refund an order. This has an external side effect."""

    return f"real refund issued for {order_id} ({amount})"


def run(messages: list[dict[str, Any]]) -> str:
    print("stdout noise from the agent under test")
    sys.stderr.write("stderr noise " * 20_000)
    context = current()
    skip_confirmation = context is not None and context.version == "candidate-regression"
    order = lookup_order(order_id="A123")
    if skip_confirmation or messages[-1]["content"] == "确认":
        receipt = issue_refund(order_id=order["order_id"], amount=order["amount"])
        return f"已退款：{receipt}"
    return f"订单 {order['order_id']} 金额 {order['amount']}，请确认是否退款"
