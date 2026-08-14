"""V1 HTTP API：只做参数投影、人工审核边界和 Service 调用。"""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query, Request, Response, status

from .api_params import EventLimit, PageLimit, PageOffset
from .bootstrap import ServiceContainer
from .capabilities import CapabilityComparisonPolicy
from .cases import CaseSelector, TestCaseCreate, TestCasePatch
from .cases.models import ReviewStatus
from .evaluations.schemas import ExternalVerdictSubmit
from .failures import (
    FailureLinksUpdate,
    FailureMonitorCreate,
    FailurePatternCreate,
    FailurePatternTransition,
    FailureSignalCreate,
    MembershipReview,
    PatternDefinitionUpdate,
)
from .gates import ReleaseGateEvaluateRequest, default_release_policy
from .jobs import ExecutionJobCreate
from .production import (
    IngestSourceCreate,
    ProductionRetentionRequest,
    TraceCaseDraftRequest,
    TraceCaseLineageReview,
)
from .profiles import ProfileCreate, ProfilePatch
from .projects import EnvironmentCreate, ProjectApiKeyCreate, ProjectCreate
from .reporting import RenderedDocument
from .reviews import (
    AlignmentRunCreate,
    AnnotationCreate,
    EvaluatorActivate,
    EvaluatorVersionCreate,
    GoldLabelResolve,
    ReviewItemCreate,
)
from .runs.models import RunEventType
from .runs.schemas import RunCasesRequest, RunCellRetryRequest
from .targets import TargetCreate, TargetPatch
from .tool_results import SampleCreate, SamplePatch
from .tool_results.models import SampleStatus

router = APIRouter(prefix="/api", tags=["AgentRig V1"])


def services(request: Request) -> ServiceContainer:
    return cast(ServiceContainer, request.app.state.services)


@router.get("/projects")
async def list_projects(
    request: Request,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).projects.list_projects(limit=limit, offset=offset)


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, value: ProjectCreate) -> object:
    return await services(request).projects.create(value)


@router.get("/projects/{project_id}")
async def get_project(request: Request, project_id: str) -> object:
    return await services(request).projects.get(project_id)


@router.get("/projects/{project_id}/environments")
async def list_project_environments(request: Request, project_id: str) -> object:
    return await services(request).projects.list_environments(project_id)


@router.post(
    "/projects/{project_id}/environments",
    status_code=status.HTTP_201_CREATED,
)
async def create_project_environment(
    request: Request,
    project_id: str,
    value: EnvironmentCreate,
) -> object:
    return await services(request).projects.create_environment(project_id, value)


@router.get("/projects/{project_id}/api-keys")
async def list_project_api_keys(request: Request, project_id: str) -> object:
    return await services(request).projects.list_api_keys(project_id)


@router.post("/projects/{project_id}/api-keys", status_code=status.HTTP_201_CREATED)
async def issue_project_api_key(
    request: Request,
    project_id: str,
    value: ProjectApiKeyCreate,
) -> object:
    return await services(request).projects.issue_api_key(project_id, value)


@router.post("/projects/{project_id}/api-keys/{key_id}:revoke")
async def revoke_project_api_key(
    request: Request,
    project_id: str,
    key_id: str,
) -> object:
    return await services(request).projects.revoke_api_key(project_id, key_id)


@router.post(
    "/projects/{project_id}/review-items",
    status_code=status.HTTP_201_CREATED,
)
async def create_review_item(
    request: Request,
    project_id: str,
    value: ReviewItemCreate,
) -> object:
    return await services(request).reviews.create_review_item(project_id, value)


@router.get("/projects/{project_id}/review-items")
async def list_review_items(
    request: Request,
    project_id: str,
    review_status: str | None = None,
    queue: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).reviews.list_review_items(
        project_id,
        status=review_status,
        queue=queue,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/review-items/{review_item_id}/annotations")
async def list_review_annotations(
    request: Request,
    project_id: str,
    review_item_id: str,
) -> object:
    return await services(request).reviews.list_annotations(project_id, review_item_id)


@router.post(
    "/projects/{project_id}/review-items/{review_item_id}/annotations",
    status_code=status.HTTP_201_CREATED,
)
async def create_review_annotation(
    request: Request,
    project_id: str,
    review_item_id: str,
    value: AnnotationCreate,
) -> object:
    return await services(request).reviews.add_annotation(project_id, review_item_id, value)


@router.post("/projects/{project_id}/review-items/{review_item_id}:resolve")
async def resolve_review_item(
    request: Request,
    project_id: str,
    review_item_id: str,
    value: GoldLabelResolve,
) -> object:
    return await services(request).reviews.resolve(project_id, review_item_id, value)


@router.get("/projects/{project_id}/evaluators/versions")
async def list_evaluator_versions(
    request: Request,
    project_id: str,
    evaluator_id: str | None = None,
) -> object:
    return await services(request).reviews.list_evaluator_versions(project_id, evaluator_id)


@router.post(
    "/projects/{project_id}/evaluators/versions",
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluator_version(
    request: Request,
    project_id: str,
    value: EvaluatorVersionCreate,
) -> object:
    return await services(request).reviews.create_evaluator_version(project_id, value)


@router.post(
    "/projects/{project_id}/evaluators/versions/{evaluator_version_id}/alignment-runs",
    status_code=status.HTTP_201_CREATED,
)
async def create_alignment_run(
    request: Request,
    project_id: str,
    evaluator_version_id: str,
    value: AlignmentRunCreate,
) -> object:
    return await services(request).reviews.run_alignment(project_id, evaluator_version_id, value)


@router.get("/projects/{project_id}/alignment-runs/{alignment_run_id}/report")
async def get_alignment_report(
    request: Request,
    project_id: str,
    alignment_run_id: str,
) -> object:
    return await services(request).reviews.get_alignment_report(project_id, alignment_run_id)


@router.post("/projects/{project_id}/evaluators/versions/{evaluator_version_id}:activate")
async def activate_evaluator_version(
    request: Request,
    project_id: str,
    evaluator_version_id: str,
    value: EvaluatorActivate,
) -> object:
    return await services(request).reviews.activate_evaluator(
        project_id, evaluator_version_id, value
    )


@router.get("/projects/{project_id}/failure-signals")
async def list_failure_signals(
    request: Request,
    project_id: str,
    category: str | None = None,
    severity: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).failures.list_signals(
        project_id,
        category=category,
        severity=severity,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects/{project_id}/failure-signals",
    status_code=status.HTTP_201_CREATED,
)
async def create_failure_signal(
    request: Request,
    project_id: str,
    value: FailureSignalCreate,
) -> object:
    return await services(request).failures.ingest_signal(project_id, value)


@router.get("/projects/{project_id}/failure-patterns")
async def list_failure_patterns(
    request: Request,
    project_id: str,
    pattern_status: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).failures.list_patterns(
        project_id,
        status=pattern_status,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects/{project_id}/failure-patterns",
    status_code=status.HTTP_201_CREATED,
)
async def create_failure_pattern(
    request: Request,
    project_id: str,
    value: FailurePatternCreate,
) -> object:
    return await services(request).failures.create_pattern(project_id, value)


@router.get("/projects/{project_id}/failure-patterns/{pattern_id}")
async def get_failure_pattern(
    request: Request,
    project_id: str,
    pattern_id: str,
) -> object:
    return await services(request).failures.get_pattern(project_id, pattern_id)


@router.post("/projects/{project_id}/failure-patterns/{pattern_id}/memberships:review")
async def review_failure_pattern_memberships(
    request: Request,
    project_id: str,
    pattern_id: str,
    value: MembershipReview,
) -> object:
    return await services(request).failures.review_memberships(project_id, pattern_id, value)


@router.post("/projects/{project_id}/failure-patterns/{pattern_id}:transition")
async def transition_failure_pattern(
    request: Request,
    project_id: str,
    pattern_id: str,
    value: FailurePatternTransition,
) -> object:
    return await services(request).failures.transition(project_id, pattern_id, value)


@router.post("/projects/{project_id}/failure-patterns/{pattern_id}/links")
async def update_failure_pattern_links(
    request: Request,
    project_id: str,
    pattern_id: str,
    value: FailureLinksUpdate,
) -> object:
    return await services(request).failures.update_links(project_id, pattern_id, value)


@router.post("/projects/{project_id}/failure-patterns/{pattern_id}/definition")
async def update_failure_pattern_definition(
    request: Request,
    project_id: str,
    pattern_id: str,
    value: PatternDefinitionUpdate,
) -> object:
    return await services(request).failures.update_definition(project_id, pattern_id, value)


@router.get("/projects/{project_id}/failure-patterns/{pattern_id}/monitors")
async def list_failure_pattern_monitors(
    request: Request,
    project_id: str,
    pattern_id: str,
) -> object:
    return await services(request).failures.list_monitors(project_id, pattern_id)


@router.post(
    "/projects/{project_id}/failure-patterns/{pattern_id}/monitors",
    status_code=status.HTTP_201_CREATED,
)
async def create_failure_pattern_monitor(
    request: Request,
    project_id: str,
    pattern_id: str,
    value: FailureMonitorCreate,
) -> object:
    return await services(request).failures.create_monitor(project_id, pattern_id, value)


@router.get("/projects/{project_id}/failure-patterns/{pattern_id}/timeline")
async def get_failure_pattern_timeline(
    request: Request,
    project_id: str,
    pattern_id: str,
) -> object:
    return await services(request).failures.timeline(project_id, pattern_id)


@router.post("/projects/{project_id}/failure-monitors/{monitor_id}/webhook:dispatch")
async def dispatch_failure_webhook(
    request: Request,
    project_id: str,
    monitor_id: str,
    idempotency_key: str,
) -> object:
    return await services(request).failures.dispatch_webhook(
        project_id, monitor_id, idempotency_key=idempotency_key
    )


@router.get("/projects/{project_id}/execution-jobs")
async def list_execution_jobs(
    request: Request,
    project_id: str,
    job_status: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).durable_jobs.list_jobs(
        project_id,
        status=job_status,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects/{project_id}/execution-jobs",
    status_code=status.HTTP_201_CREATED,
)
async def create_execution_job(
    request: Request,
    project_id: str,
    value: ExecutionJobCreate,
) -> object:
    return await services(request).durable_jobs.enqueue(project_id, value)


@router.get("/projects/{project_id}/execution-jobs/{job_id}")
async def get_execution_job(
    request: Request,
    project_id: str,
    job_id: str,
) -> object:
    return await services(request).durable_jobs.get(project_id, job_id)


@router.get("/projects/{project_id}/execution-jobs/{job_id}/attempts")
async def list_execution_attempts(
    request: Request,
    project_id: str,
    job_id: str,
) -> object:
    return await services(request).durable_jobs.list_attempts(project_id, job_id)


@router.post("/projects/{project_id}/execution-jobs/{job_id}:cancel")
async def cancel_execution_job(
    request: Request,
    project_id: str,
    job_id: str,
) -> object:
    container = services(request)
    job = await container.durable_jobs.cancel(project_id, job_id)
    await container.durable_worker.finalize_run(project_id, job.run_id)
    return job


@router.get("/projects/{project_id}/production/ingest-sources")
async def list_ingest_sources(request: Request, project_id: str) -> object:
    return await services(request).production.list_sources(project_id)


@router.post(
    "/projects/{project_id}/production/ingest-sources",
    status_code=status.HTTP_201_CREATED,
)
async def create_ingest_source(
    request: Request,
    project_id: str,
    value: IngestSourceCreate,
) -> object:
    await services(request).projects.get(project_id)
    return await services(request).production.create_source(project_id, value)


@router.post("/projects/{project_id}/production/ingest-sources/{source_id}:enable")
async def enable_ingest_source(
    request: Request,
    project_id: str,
    source_id: str,
) -> object:
    return await services(request).production.set_source_enabled(
        project_id,
        source_id,
        enabled=True,
    )


@router.post("/projects/{project_id}/production/ingest-sources/{source_id}:disable")
async def disable_ingest_source(
    request: Request,
    project_id: str,
    source_id: str,
) -> object:
    return await services(request).production.set_source_enabled(
        project_id,
        source_id,
        enabled=False,
    )


@router.get("/projects/{project_id}/production/sessions")
async def list_production_sessions(
    request: Request,
    project_id: str,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).production.list_sessions(
        project_id,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/production/traces")
async def list_production_traces(
    request: Request,
    project_id: str,
    environment: str | None = None,
    service_name: str | None = None,
    trace_status: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).production.list_traces(
        project_id,
        environment=environment,
        service_name=service_name,
        trace_status=trace_status,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/production/traces/{trace_id}")
async def get_production_trace(
    request: Request,
    project_id: str,
    trace_id: str,
) -> object:
    return await services(request).production.get_trace(project_id, trace_id)


@router.get("/projects/{project_id}/production/traces/{trace_id}/spans")
async def list_production_spans(
    request: Request,
    project_id: str,
    trace_id: str,
) -> object:
    return await services(request).production.list_spans(project_id, trace_id)


@router.post("/projects/{project_id}/production/retention:run")
async def run_production_retention(
    request: Request,
    project_id: str,
    value: ProductionRetentionRequest,
) -> object:
    return await services(request).production.run_retention(project_id, value)


@router.post("/projects/{project_id}/production/traces/{trace_id}/case-drafts:preview")
async def preview_trace_case_draft(
    request: Request,
    project_id: str,
    trace_id: str,
    value: TraceCaseDraftRequest,
) -> object:
    return await services(request).production.preview_case_draft(
        project_id,
        trace_id,
        value,
    )


@router.post(
    "/projects/{project_id}/production/traces/{trace_id}/case-drafts",
    status_code=status.HTTP_201_CREATED,
)
async def create_trace_case_draft(
    request: Request,
    project_id: str,
    trace_id: str,
    value: TraceCaseDraftRequest,
) -> object:
    return await services(request).production.create_case_draft(
        project_id,
        trace_id,
        value,
    )


@router.post("/projects/{project_id}/production/case-lineages/{lineage_id}:review")
async def review_trace_case_lineage(
    request: Request,
    project_id: str,
    lineage_id: str,
    value: TraceCaseLineageReview,
) -> object:
    return await services(request).production.review_case_lineage(
        project_id,
        lineage_id,
        value,
    )


@router.get("/test-cases")
async def list_test_cases(
    request: Request,
    capabilities: Annotated[list[str] | None, Query()] = None,
    tool_names: Annotated[list[str] | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    review_status: Annotated[list[ReviewStatus] | None, Query()] = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
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
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).targets.list_targets(limit=limit, offset=offset)


@router.post("/targets", status_code=status.HTTP_201_CREATED)
async def create_target(request: Request, value: TargetCreate) -> object:
    return await services(request).targets.create(value)


@router.get("/targets/schema")
async def get_target_schema(
    request: Request,
    driver_type: str | None = None,
) -> object:
    return services(request).targets.schema(driver_type)


@router.get("/driver-types")
async def list_driver_types(request: Request) -> object:
    return services(request).targets.list_driver_types()


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


@router.post("/targets/{target_id}:probe-capabilities")
async def probe_target_capabilities(
    request: Request,
    target_id: str,
    version: str | None = None,
) -> object:
    return await services(request).targets.probe_capabilities(
        target_id,
        version=version,
    )


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


@router.get("/targets/{target_id}/export/preview")
async def preview_target_export(request: Request, target_id: str) -> object:
    return await services(request).reporting.export_preview(target_id)


@router.get("/targets/{target_id}/export")
async def export_target_data(
    request: Request,
    target_id: str,
    export_format: Annotated[
        Literal["json", "markdown", "html"],
        Query(alias="format"),
    ] = "json",
) -> Response:
    reporting = services(request).reporting
    bundle = await reporting.target_export(target_id)
    return _download_response(reporting.render_target_export(bundle, export_format))


@router.get("/execution-profiles")
async def list_execution_profiles(
    request: Request,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).profiles.list_profiles(limit=limit, offset=offset)


@router.post("/execution-profiles", status_code=status.HTTP_201_CREATED)
async def create_execution_profile(request: Request, value: ProfileCreate) -> object:
    return await services(request).profiles.create(value)


@router.get("/execution-profiles/schema")
async def get_execution_profile_schema() -> dict[str, object]:
    return ProfileCreate.model_json_schema()


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
    limit: PageLimit = 50,
    offset: PageOffset = 0,
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


@router.get("/samples/schema")
async def get_sample_schema() -> dict[str, object]:
    return SampleCreate.model_json_schema()


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


@router.post("/runs/preview")
async def preview_run_cases(request: Request, value: RunCasesRequest) -> object:
    """Resolve the immutable Manifest without creating a Run."""

    return await services(request).runs.preview_run_cases(value)


@router.get("/runs/schema")
async def get_run_cases_schema() -> dict[str, object]:
    return RunCasesRequest.model_json_schema()


@router.get("/runs")
async def list_runs(
    request: Request,
    target_id: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).runs.list_runs(
        target_id=target_id,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> object:
    return await services(request).runs.get_run(run_id)


@router.get("/runs/{run_id}/summary")
async def get_run_summary(request: Request, run_id: str) -> object:
    return await services(request).runs.get_run_summary(run_id)


@router.get("/runs/{run_id}/report")
async def get_run_report(
    request: Request,
    run_id: str,
    report_format: Annotated[
        Literal["json", "markdown"],
        Query(alias="format"),
    ] = "json",
) -> object:
    reporting = services(request).reporting
    report = await reporting.run_report(run_id)
    if report_format == "markdown":
        return _download_response(reporting.render_run_report(report))
    return report


@router.get("/runs/{run_id}/quality-report")
async def get_quality_report(
    request: Request,
    run_id: str,
    report_format: Annotated[
        Literal["json", "markdown"],
        Query(alias="format"),
    ] = "json",
) -> object:
    reporting = services(request).reporting
    report = await reporting.quality_report(run_id)
    if report_format == "markdown":
        return _download_response(reporting.render_quality_report(report))
    return report


@router.get("/runs/{run_id}/comparison-report")
async def get_comparison_report(
    request: Request,
    run_id: str,
    report_format: Annotated[
        Literal["json", "markdown"],
        Query(alias="format"),
    ] = "json",
) -> object:
    reporting = services(request).reporting
    report = await reporting.comparison_report(run_id)
    if report_format == "markdown":
        return _download_response(reporting.render_comparison_report(report))
    return report


@router.get("/release-policies/default")
async def get_default_release_policy() -> object:
    return default_release_policy()


@router.post("/runs/{run_id}/release-gate:evaluate")
async def evaluate_release_gate(
    request: Request,
    run_id: str,
    value: ReleaseGateEvaluateRequest,
    report_format: Annotated[
        Literal["json", "markdown"],
        Query(alias="format"),
    ] = "json",
) -> object:
    gate = services(request).release_gates
    result = await gate.evaluate(run_id, value.policy)
    if report_format == "markdown":
        return _download_response(gate.render_markdown(result))
    return result


@router.get("/runs/{run_id}/safety-report")
async def get_runtime_safety_report(
    request: Request,
    run_id: str,
    suite_id: str = "agentscope-runtime-safety",
    version: str = "1.0.0",
) -> object:
    return await services(request).safety.report(
        run_id,
        suite_id=suite_id,
        version=version,
    )


@router.post("/runs/{run_id}/safety-gate:evaluate")
async def evaluate_runtime_safety_gate(
    request: Request,
    run_id: str,
    suite_id: str = "agentscope-runtime-safety",
    version: str = "1.0.0",
) -> object:
    return await services(request).safety.gate(
        run_id,
        suite_id=suite_id,
        version=version,
    )


@router.get("/runs/{run_id}/case-runs")
async def list_case_runs(
    request: Request,
    run_id: str,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).runs.list_case_runs(
        run_id,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}/cells")
async def list_run_cells(
    request: Request,
    run_id: str,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> object:
    return await services(request).runs.list_run_cells(
        run_id,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}/cells/{cell_id}")
async def get_run_cell(request: Request, run_id: str, cell_id: str) -> object:
    return await services(request).runs.get_run_cell(run_id, cell_id)


@router.post("/runs/{run_id}/retry-cells", status_code=status.HTTP_202_ACCEPTED)
async def retry_run_cells(
    request: Request,
    run_id: str,
    value: RunCellRetryRequest,
) -> object:
    return await services(request).runs.retry_run_cells(run_id, value)


@router.get("/case-runs/{case_run_id}")
async def get_case_run(request: Request, case_run_id: str) -> object:
    return await services(request).runs.get_case_run(case_run_id)


@router.get("/case-runs/{case_run_id}/capability-snapshot")
async def get_case_run_capability_snapshot(
    request: Request,
    case_run_id: str,
) -> object:
    return await services(request).runs.get_capability_snapshot(case_run_id)


@router.post("/case-runs/{case_run_id}/capability-diff/{other_case_run_id}")
async def compare_case_run_capabilities(
    request: Request,
    case_run_id: str,
    other_case_run_id: str,
    value: CapabilityComparisonPolicy | None = None,
) -> object:
    return await services(request).runs.compare_capability_snapshots(
        case_run_id,
        other_case_run_id,
        value,
    )


@router.get("/case-runs/{case_run_id}/capability-diff/{other_case_run_id}")
async def get_case_run_capability_diff(
    request: Request,
    case_run_id: str,
    other_case_run_id: str,
) -> object:
    return await services(request).runs.compare_capability_snapshots(
        case_run_id,
        other_case_run_id,
    )


@router.get("/case-runs/{case_run_id}/events")
async def list_case_run_events(
    request: Request,
    case_run_id: str,
    event_types: Annotated[list[RunEventType] | None, Query()] = None,
    limit: EventLimit = 100,
    offset: PageOffset = 0,
) -> object:
    return await services(request).runs.list_case_run_events(
        case_run_id,
        event_types=event_types,
        limit=limit,
        offset=offset,
    )


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


def _download_response(document: RenderedDocument) -> Response:
    return Response(
        content=document.content,
        media_type=document.media_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )
