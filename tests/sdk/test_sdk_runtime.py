"""agentrig.sdk 在被测进程内的工具接管语义。"""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from agentrig.sdk import current, tool
from agentrig.sdk._runtime import HarnessClosedError, HarnessContext, HarnessRuntime, activate
from agentrig.sdk._tools import ToolSpec, describe_callable


class _AgentRigStub(io.StringIO):
    """记录协议行；按工具名立即回灌结果，模拟 AgentRig 的 Provider 链。"""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self.results = results
        self.runtime: HarnessRuntime | None = None

    def write(self, text: str) -> int:
        event = json.loads(text)
        self.events.append(event)
        if event["type"] == "tool_calls" and self.results is not None:
            assert self.runtime is not None
            for call in event["tool_calls"]:
                self.runtime.resolve(
                    [{"tool_call_id": call["id"], "result": self.results[call["name"]]}]
                )
        return len(text)


@pytest.fixture
def harness() -> Iterator[tuple[HarnessRuntime, _AgentRigStub]]:
    stub = _AgentRigStub({"lookup": {"status": "shipped"}, "summarize": {"text": "ok"}})
    runtime = HarnessRuntime(stub)
    stub.runtime = runtime
    activate(runtime)
    try:
        yield runtime, stub
    finally:
        activate(None)


class Order(BaseModel):
    status: str


calls: list[str] = []


@tool
def lookup(order_id: str, *, verbose: bool = False) -> dict[str, Any]:
    """Look up an order."""

    calls.append(order_id)
    return {"status": "real"}


@tool(name="summarize")
def summarize_text(text: str) -> str:
    calls.append(text)
    return "real summary"


@tool
async def fetch_order(order_id: str) -> Order:
    calls.append(order_id)
    return Order(status="real")


def test_tool_is_a_plain_call_outside_the_harness() -> None:
    calls.clear()
    assert current() is None
    assert lookup("A1") == {"status": "real"}
    assert summarize_text("x") == "real summary"
    assert calls == ["A1", "x"]


def test_controlled_tool_returns_agentrig_result_without_running_original(
    harness: tuple[HarnessRuntime, _AgentRigStub],
) -> None:
    _, stub = harness
    calls.clear()

    assert lookup("A1", verbose=True) == {"status": "shipped"}
    # 声明返回 str 的工具收到结构化 Fixture 时还原为 JSON 文本。
    assert summarize_text(text="x") == '{"text": "ok"}'
    assert calls == []
    first = stub.events[0]["tool_calls"][0]
    assert first["name"] == "lookup"
    assert first["arguments"] == {"order_id": "A1", "verbose": True}
    assert first["result_schema"]["type"] == "object"
    assert "Look up an order." in first["result_schema"]["description"]
    # 标量返回值不约束结果类型，只给 Curator 说明工具用途。
    assert "type" not in stub.events[1]["tool_calls"][0]["result_schema"]


async def test_async_tool_restores_pydantic_return_type(
    harness: tuple[HarnessRuntime, _AgentRigStub],
) -> None:
    _, stub = harness
    stub.results = {"fetch_order": {"status": "simulated"}}
    calls.clear()

    order = await fetch_order("A2")

    assert order == Order(status="simulated")
    assert calls == []


def test_observe_mode_runs_original_and_reports_result(
    harness: tuple[HarnessRuntime, _AgentRigStub],
) -> None:
    runtime, stub = harness
    stub.results = None
    runtime.context = HarnessContext(tool_mode="observe_only")
    calls.clear()

    assert lookup("A3") == {"status": "real"}

    assert calls == ["A3"]
    assert [event["type"] for event in stub.events] == ["tool_calls", "tool_result_observed"]
    assert stub.events[1]["payload"] == {
        "tool_call_id": stub.events[0]["tool_calls"][0]["id"],
        "tool_name": "lookup",
        "result": {"status": "real"},
    }


def test_observe_mode_reports_tool_errors_and_reraises(
    harness: tuple[HarnessRuntime, _AgentRigStub],
) -> None:
    runtime, stub = harness
    stub.results = None
    runtime.context = HarnessContext(tool_mode="observe_only")

    @tool
    def explode() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        explode()
    assert stub.events[-1]["payload"]["error"] == "ValueError: boom"


def test_close_fails_calls_still_waiting_for_results(
    harness: tuple[HarnessRuntime, _AgentRigStub],
) -> None:
    runtime, stub = harness
    stub.results = None
    errors: list[BaseException] = []

    def call() -> None:
        try:
            lookup("A4")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=call)
    worker.start()
    while not stub.events:
        pass
    runtime.close()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], HarnessClosedError)


def test_describe_callable_reports_input_and_output_schema() -> None:
    def search(query: str, limit: int = 10, *args: Any, **kwargs: Any) -> list[str]:
        """Search the catalog."""

        return []

    spec = describe_callable(search)

    assert spec == ToolSpec(
        name="search",
        description="Search the catalog.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"],
        },
        output_schema={"type": "array", "items": {"type": "string"}},
    )
    assert spec.result_schema()["type"] == "array"
