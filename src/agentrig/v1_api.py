"""V1 HTTP API：只做参数投影、人工审核边界和 Service 调用。"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query, Request, Response, status

from .bootstrap import ServiceContainer
from .cases import CaseSelector, TestCaseCreate, TestCasePatch
from .cases.models import ReviewStatus
from .evaluations.schemas import ExternalVerdictSubmit
from .profiles import ProfileCreate, ProfilePatch
from .runs.schemas import RunCasesRequest
from .targets import TargetCreate, TargetPatch
from .tool_results import SampleCreate, SamplePatch
from .tool_results.models import SampleStatus

router = APIRouter(prefix="/api", tags=["AgentRig V1"])


def services(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.services)


@router.get("/test-cases")
async def list_test_cases(
    request: Request,
    capabilities: Annotated[list[str] | None, Query()] = None,
    tool_names: Annotated[list[str] | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    review_status: Annotated[list[ReviewStatus] | None, Query()] = None,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).cases.list_cases(
        CaseSelector(
            capabilities=capabilities or [],
            tool_names=tool_names or [],
            tags=tags or [],
            review_status=review_status or [],
        ),
        limit=limit,
        offset=offset,
    )


@router.get("/test-cases/schema")
async def get_test_case_schema() -> dict[str, object]:
    return TestCaseCreate.model_json_schema()


@router.post("/test-cases", status_code=status.HTTP_201_CREATED)
async def create_test_case(request: Request, value: TestCaseCreate) -> object:
    return await services(request).cases.create(value)


@router.get("/test-cases/{case_id}")
async def get_test_case(request: Request, case_id: str) -> object:
    return await services(request).cases.get(case_id)


@router.patch("/test-cases/{case_id}")
async def update_test_case(
    request: Request,
    case_id: str,
    value: TestCasePatch,
) -> object:
    return await services(request).cases.update(case_id, value)


@router.delete("/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(request: Request, case_id: str) -> Response:
    await services(request).cases.delete(case_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test-cases/{case_id}/review")
async def review_test_case(
    request: Request,
    case_id: str,
    review_status: Literal["approved", "rejected"],
) -> object:
    return await services(request).cases.review(case_id, ReviewStatus(review_status))


@router.get("/tags")
async def list_tags(request: Request) -> object:
    return await services(request).cases.list_tags()


@router.get("/targets")
async def list_targets(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).targets.list_targets(limit=limit, offset=offset)


@router.post("/targets", status_code=status.HTTP_201_CREATED)
async def create_target(request: Request, value: TargetCreate) -> object:
    return await services(request).targets.create(value)


@router.get("/targets/{target_id}")
async def get_target(request: Request, target_id: str) -> object:
    return await services(request).targets.get(target_id)


@router.post("/targets/{target_id}/check")
async def check_target(
    request: Request,
    target_id: str,
    version: str | None = None,
) -> object:
    return await services(request).targets.check(target_id, version=version)


@router.patch("/targets/{target_id}")
async def update_target(
    request: Request,
    target_id: str,
    value: TargetPatch,
) -> object:
    return await services(request).targets.update(target_id, value)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(request: Request, target_id: str) -> Response:
    await services(request).targets.delete(target_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/execution-profiles")
async def list_execution_profiles(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).profiles.list_profiles(limit=limit, offset=offset)


@router.post("/execution-profiles", status_code=status.HTTP_201_CREATED)
async def create_execution_profile(request: Request, value: ProfileCreate) -> object:
    return await services(request).profiles.create(value)


@router.get("/execution-profiles/{profile_id}")
async def get_execution_profile(request: Request, profile_id: str) -> object:
    return await services(request).profiles.get(profile_id)


@router.patch("/execution-profiles/{profile_id}")
async def update_execution_profile(
    request: Request,
    profile_id: str,
    value: ProfilePatch,
) -> object:
    return await services(request).profiles.update(profile_id, value)


@router.delete(
    "/execution-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_execution_profile(request: Request, profile_id: str) -> Response:
    await services(request).profiles.delete(profile_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/samples")
async def list_samples(
    request: Request,
    sample_status: SampleStatus | None = None,
    tool_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).samples.list_samples(
        status=sample_status,
        tool_name=tool_name,
        limit=limit,
        offset=offset,
    )


@router.post("/samples", status_code=status.HTTP_201_CREATED)
async def create_sample(request: Request, value: SampleCreate) -> object:
    return await services(request).samples.create(value)


@router.get("/samples/{sample_id}")
async def get_sample(request: Request, sample_id: str) -> object:
    return await services(request).samples.get(sample_id)


@router.patch("/samples/{sample_id}")
async def update_sample(
    request: Request,
    sample_id: str,
    value: SamplePatch,
) -> object:
    return await services(request).samples.update(sample_id, value)


@router.delete("/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sample(request: Request, sample_id: str) -> Response:
    await services(request).samples.delete(sample_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/samples/{sample_id}/review")
async def review_sample(
    request: Request,
    sample_id: str,
    sample_status: Literal["approved", "disabled"],
) -> object:
    return await services(request).samples.review(sample_id, SampleStatus(sample_status))


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def run_cases(request: Request, value: RunCasesRequest) -> object:
    return await services(request).runs.run_cases(value)


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).runs.list_runs(limit=limit, offset=offset)


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> object:
    return await services(request).runs.get_run(run_id)


@router.get("/runs/{run_id}/case-runs")
async def list_case_runs(
    request: Request,
    run_id: str,
    limit: int = 50,
    offset: int = 0,
) -> object:
    return await services(request).runs.list_case_runs(
        run_id,
        limit=limit,
        offset=offset,
    )


@router.get("/case-runs/{case_run_id}")
async def get_case_run(request: Request, case_run_id: str) -> object:
    return await services(request).runs.get_case_run(case_run_id)


@router.put("/case-runs/{case_run_id}/external-verdict")
async def submit_external_verdict(
    request: Request,
    case_run_id: str,
    value: ExternalVerdictSubmit,
) -> object:
    return await services(request).runs.submit_external_verdict(case_run_id, value)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(request: Request, run_id: str) -> object:
    return await services(request).runs.cancel_run(run_id)
