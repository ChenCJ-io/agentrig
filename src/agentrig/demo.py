"""AgentRig V1 一键纵向验收演示。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from .bootstrap import ServiceContainer
from .cases import TestCaseCreate
from .config import Settings
from .infrastructure.database import Database
from .profiles import ProfileCreate
from .runs.schemas import RunCasesRequest
from .targets import TargetCreate
from .targets.drivers import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverRegistry,
    DriverSession,
    ToolCall,
    ToolResult,
)


class DemoDriver:
    """演示专用确定性 Driver：先调用 search，再根据 Fixture 回复。"""

    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        return DriverSession(id=f"demo-{context.case_run_id}")

    async def send_user_message(
        self,
        session: DriverSession,
        message: str,
    ) -> AsyncIterator[DriverEvent]:
        del session
        yield DriverEvent(
            type=DriverEventType.TOOL_CALLS,
            tool_calls=[
                ToolCall(
                    id="demo-call",
                    name="search",
                    arguments={"query": message},
                    result_schema={
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}},
                    },
                )
            ],
        )

    async def send_tool_results(
        self,
        session: DriverSession,
        results: list[ToolResult],
    ) -> AsyncIterator[DriverEvent]:
        del session
        count = len(results[0].result["items"])
        yield DriverEvent(
            type=DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
            text=f"搜索完成，共 {count} 条结果。",
        )
        yield DriverEvent(type=DriverEventType.COMPLETED)

    async def cancel(self, session: DriverSession) -> None:
        session.state["cancelled"] = True

    async def close(self, session: DriverSession) -> None:
        session.state["closed"] = True


async def run_demo() -> int:
    registry = DriverRegistry()
    registry.register("demo", DemoDriver)
    services = ServiceContainer.build(
        Settings(),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=registry,
    )
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_demo",
                    "name": "搜索结果回灌",
                    "supported_versions": ["v1"],
                    "primary_evaluator": "rule",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": "AgentRig",
                            "fixtures": [
                                {
                                    "tool_name": "search",
                                    "match_arguments": {"query": "AgentRig"},
                                    "result": {"items": [{"title": "AgentRig V1"}]},
                                }
                            ],
                            "assertions": [
                                {"kind": "tool_called", "tool_name": "search"},
                                {"kind": "text_contains", "value": "1 条结果"},
                                {"kind": "no_execution_error"},
                            ],
                        }
                    ],
                }
            )
        )
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_demo",
                    "name": "Demo Agent",
                    "driver_type": "demo",
                    "versions": [{"version": "v1"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_demo",
                    "name": "Core Demo",
                    "config": {
                        "tool_mode": "controlled",
                        "provider_chain": [{"name": "fixture"}],
                        "primary_evaluator": "rule",
                    },
                }
            )
        )
        submitted = await services.runs.run_cases(
            RunCasesRequest.model_validate(
                {
                    "case_ids": ["case_demo"],
                    "targets": [{"target_id": "target_demo"}],
                    "profile_id": "profile_demo",
                }
            )
        )
        await services.scheduler.wait(submitted.run_id)
        run = await services.runs.get_run(submitted.run_id)
        page = await services.runs.list_case_runs(submitted.run_id)
        detail = await services.runs.get_case_run(page.items[0].id)

        print("AgentRig V1 Demo")
        print(f"Run       : {run.id} ({run.status})")
        print(f"CaseRun   : {detail.id} ({detail.status})")
        print(f"Evaluation: {detail.evaluation_state}")
        print(f"Events    : {len(detail.events)}")
        print(f"Evaluators: {[item.evaluator_type.value for item in detail.evaluations]}")
        return 0 if detail.evaluation_state == "pass" else 1
    finally:
        await services.close()
