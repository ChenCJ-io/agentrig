"""三个 V1 Demo 共用的最小执行辅助。"""

from __future__ import annotations

from agentrig.bootstrap import ServiceContainer
from agentrig.runs.schemas import CaseRunDetail, RunCasesRequest


async def execute_one(
    services: ServiceContainer,
    *,
    case_id: str,
    target_id: str,
    profile_id: str,
) -> CaseRunDetail:
    submitted = await services.runs.run_cases(
        RunCasesRequest.model_validate(
            {
                "case_ids": [case_id],
                "targets": [{"target_id": target_id}],
                "profile_id": profile_id,
            }
        )
    )
    await services.scheduler.wait(submitted.run_id)
    page = await services.runs.list_case_runs(submitted.run_id)
    return await services.runs.get_case_run(page.items[0].id)


def print_result(title: str, detail: CaseRunDetail) -> None:
    providers = [
        event.payload.get("source")
        for event in detail.events
        if event.event_type.value == "tool_result"
    ]
    print(title)
    print(f"  CaseRun   : {detail.id}")
    print(f"  Execution : {detail.status.value}")
    print(f"  Evaluation: {detail.evaluation_state}")
    print(f"  Providers : {providers}")
    print(
        "  Evaluators: "
        f"{[record.evaluator_type.value for record in detail.evaluations]}"
    )
