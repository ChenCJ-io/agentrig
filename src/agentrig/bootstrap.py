"""AgentRig V1 Core 与 V2 助手服务的唯一装配点。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .agents import (
    EvidenceJudge,
    ModelClient,
    OpenAICompatibleModelClient,
    SimulationCurator,
)
from .assistant import AssistantService, EvaluationPlanService
from .assistant.basic_runtime import BasicAssistantRuntime
from .assistant.run_notifier import AssistantRunNotifier
from .cases import CaseService
from .config import Settings, get_settings
from .evaluations.rule_evaluator import RuleEvaluator
from .evaluations.service import EvaluationService
from .failures import FailureGovernanceService
from .gates import ReleaseGateService
from .infrastructure.database import Database
from .infrastructure.database.repositories import (
    SqlAssistantRepository,
    SqlCaseRepository,
    SqlEvaluationRepository,
    SqlProfileRepository,
    SqlRunRepository,
    SqlSampleRepository,
    SqlTargetChatRepository,
    SqlTargetRepository,
    SqlToolCallEvidenceReader,
)
from .infrastructure.http_policy import TargetHttpPolicy
from .infrastructure.secrets import SecretResolver
from .jobs import DurableJobService, DurableWorker
from .observability import RunOtlpExporter
from .production import ProductionEvidenceService
from .production.gateway import GatewayService
from .profiles import ProfileService
from .profiles.resolver import ProfileResolver
from .projects import ProjectService
from .proxy.backend import BackendRegistry
from .proxy.scoped import ProxyScopeRegistry
from .reporting import ReportingService
from .reviews import ReviewAlignmentService
from .runs.event_recorder import EventRecorder
from .runs.executor import CaseExecutor
from .runs.planner import RunPlanner
from .runs.redactor import Redactor
from .runs.scheduler import RunScheduler
from .runs.service import RunService
from .safety import SafetyService
from .target_chat import TargetChatService
from .targets import TargetService
from .targets.drivers import DriverRegistry
from .tool_results import SampleService
from .tool_results.providers import McpBackendRealToolClient, RealToolClient
from .tool_results.validator import ToolResultValidator


@dataclass
class ServiceContainer:
    settings: Settings
    database: Database
    cases: CaseService
    targets: TargetService
    profiles: ProfileService
    projects: ProjectService
    production: ProductionEvidenceService
    gateway: GatewayService
    reviews: ReviewAlignmentService
    failures: FailureGovernanceService
    samples: SampleService
    assistant: AssistantService
    evaluation_plans: EvaluationPlanService
    basic_assistant: BasicAssistantRuntime
    target_chats: TargetChatService
    runs: RunService
    reporting: ReportingService
    release_gates: ReleaseGateService
    safety: SafetyService
    durable_jobs: DurableJobService
    durable_worker: DurableWorker
    scheduler: RunScheduler
    drivers: DriverRegistry
    proxy_scopes: ProxyScopeRegistry
    backend_registry: BackendRegistry
    server_api_token: str | None

    @classmethod
    def build(
        cls,
        settings: Settings | None = None,
        *,
        database: Database | None = None,
        drivers: DriverRegistry | None = None,
        model_client: ModelClient | None = None,
        real_tool_client: RealToolClient | None = None,
        backend_registry: BackendRegistry | None = None,
        gateway_transport: httpx.AsyncBaseTransport | None = None,
    ) -> ServiceContainer:
        resolved_settings = settings or get_settings()
        resolved_database = database or Database(resolved_settings.database.url)
        driver_registry = drivers or DriverRegistry(
            python_allowlist=resolved_settings.execution.python_driver_allowlist,
            subprocess_allowlist=resolved_settings.execution.subprocess_allowlist,
        )
        resolved_model_client = model_client or OpenAICompatibleModelClient()
        secret_resolver = SecretResolver()
        server_api_token = secret_resolver.resolve(resolved_settings.server.api_token_ref)
        proxy_scopes = ProxyScopeRegistry()
        resolved_backend_registry = backend_registry or BackendRegistry()
        resolved_real_tool_client = real_tool_client or McpBackendRealToolClient(
            resolved_backend_registry
        )

        case_repository = SqlCaseRepository(resolved_database)
        target_repository = SqlTargetRepository(resolved_database)
        profile_repository = SqlProfileRepository(resolved_database)
        sample_repository = SqlSampleRepository(resolved_database)
        run_repository = SqlRunRepository(resolved_database)
        evaluation_repository = SqlEvaluationRepository(resolved_database)
        assistant_repository = SqlAssistantRepository(resolved_database)
        target_chat_repository = SqlTargetChatRepository(resolved_database)

        cases = CaseService(case_repository)
        targets = TargetService(
            target_repository,
            drivers=driver_registry,
            secrets=secret_resolver,
            http_policy=TargetHttpPolicy(resolved_settings.target_network),
        )
        profiles = ProfileService(profile_repository)
        projects = ProjectService(resolved_database)
        samples = SampleService(
            sample_repository,
            evidence_reader=SqlToolCallEvidenceReader(resolved_database),
        )
        assistant = AssistantService(assistant_repository)
        redactor = Redactor(
            sensitive_keys=resolved_settings.evidence.sensitive_keys,
            sensitive_paths=resolved_settings.evidence.sensitive_paths,
        )
        production = ProductionEvidenceService(
            resolved_database,
            config=resolved_settings.production_evidence,
            redactor=redactor,
            http_policy=TargetHttpPolicy(resolved_settings.target_network),
        )
        gateway = GatewayService(
            production,
            secrets_resolver=secret_resolver,
            transport=gateway_transport,
        )
        reviews = ReviewAlignmentService(resolved_database)
        failures = FailureGovernanceService(
            resolved_database,
            secrets=secret_resolver,
            http_policy=TargetHttpPolicy(resolved_settings.target_network),
        )
        simulation_curator = SimulationCurator(
            resolved_model_client,
            secret_resolver,
        )
        evidence_judge = EvidenceJudge(
            resolved_model_client,
            secret_resolver,
        )
        durable_jobs = DurableJobService(
            resolved_database,
            resolved_settings.execution,
        )
        recorder = EventRecorder(
            run_repository,
            redactor,
            external_side_effect_listener=(durable_jobs.mark_external_side_effect_by_attempt),
        )
        validator = ToolResultValidator(
            max_bytes=resolved_settings.evidence.max_event_payload_bytes,
        )
        target_chats = TargetChatService(
            targets=targets,
            cases=cases,
            profiles=profiles,
            drivers=driver_registry,
            secrets=secret_resolver,
            samples=sample_repository,
            sample_service=samples,
            repository=target_chat_repository,
            validator=validator,
            curator=simulation_curator,
            redactor=redactor,
            real_tool_client=resolved_real_tool_client,
            real_tool_allowlist=resolved_settings.execution.real_tool_allowlist,
        )
        executor = CaseExecutor(
            runs=run_repository,
            evaluations=evaluation_repository,
            samples=sample_repository,
            drivers=driver_registry,
            secrets=secret_resolver,
            recorder=recorder,
            validator=validator,
            simulation_curator=simulation_curator,
            evidence_judge=evidence_judge,
            real_tool_client=resolved_real_tool_client,
            real_tool_allowlist=resolved_settings.execution.real_tool_allowlist,
            rule_evaluator=RuleEvaluator(),
            proxy_scopes=proxy_scopes,
            proxy_public_url=_proxy_public_url(resolved_settings),
            server_api_token=server_api_token,
        )
        scheduler = RunScheduler(run_repository, executor)
        durable_worker = DurableWorker(
            durable_jobs,
            executor,
            run_repository,
            resolved_settings.execution,
        )
        planner = RunPlanner(
            cases=cases,
            targets=targets,
            profiles=profiles,
            profile_resolver=ProfileResolver(resolved_settings),
            drivers=driver_registry,
            runs=run_repository,
            max_cases_per_run=resolved_settings.execution.max_cases_per_run,
            max_planned_case_runs=resolved_settings.execution.max_planned_case_runs,
        )
        runs = RunService(
            planner=planner,
            scheduler=scheduler,
            repository=run_repository,
            evaluations=EvaluationService(
                evaluation_repository,
                run_repository,
            ),
            durable_jobs=durable_jobs,
            durable_worker=durable_worker,
            durable_scheduler_enabled=(resolved_settings.execution.durable_scheduler_enabled),
        )
        reporting = ReportingService(
            cases=case_repository,
            targets=target_repository,
            samples=sample_repository,
            runs=run_repository,
            redactor=redactor,
            max_report_case_runs=resolved_settings.reporting.max_report_case_runs,
            max_export_records=resolved_settings.reporting.max_export_records,
        )
        release_gates = ReleaseGateService(reporting)
        safety = SafetyService(
            run_repository,
            max_case_runs=resolved_settings.reporting.max_report_case_runs,
        )
        evaluation_plans = EvaluationPlanService(
            repository=assistant_repository,
            assistant=assistant,
            runs=runs,
        )
        basic_assistant = BasicAssistantRuntime(
            config=resolved_settings.assistant.basic_provider,
            model_client=resolved_model_client,
            secrets=secret_resolver,
            assistant=assistant,
            plans=evaluation_plans,
            cases=cases,
            targets=targets,
            profiles=profiles,
            runs=runs,
        )
        run_notifier = AssistantRunNotifier(
            repository=assistant_repository,
            assistant=assistant,
            basic_runtime=basic_assistant,
        )
        scheduler.add_completion_listener(run_notifier)
        durable_worker.add_completion_listener(run_notifier)
        if resolved_settings.run_otlp_export.enabled:
            export_headers = {
                name: secret_resolver.resolve(reference) or ""
                for name, reference in (
                    resolved_settings.run_otlp_export.header_secret_refs.items()
                )
            }
            run_otlp_exporter = RunOtlpExporter(
                resolved_settings.run_otlp_export,
                headers=export_headers,
            )
            scheduler.add_completion_listener(run_otlp_exporter)
            durable_worker.add_completion_listener(run_otlp_exporter)
        return cls(
            settings=resolved_settings,
            database=resolved_database,
            cases=cases,
            targets=targets,
            profiles=profiles,
            projects=projects,
            production=production,
            gateway=gateway,
            reviews=reviews,
            failures=failures,
            samples=samples,
            assistant=assistant,
            evaluation_plans=evaluation_plans,
            basic_assistant=basic_assistant,
            target_chats=target_chats,
            runs=runs,
            reporting=reporting,
            release_gates=release_gates,
            safety=safety,
            durable_jobs=durable_jobs,
            durable_worker=durable_worker,
            scheduler=scheduler,
            drivers=driver_registry,
            proxy_scopes=proxy_scopes,
            backend_registry=resolved_backend_registry,
            server_api_token=server_api_token,
        )

    async def initialize(self) -> None:
        await self.database.initialize_schema()
        await self.projects.ensure_default()
        if self.settings.execution.durable_scheduler_enabled:
            await self.durable_worker.recover_expired()
            await self.target_chats.mark_interrupted()
        else:
            await self._mark_interrupted()

    async def close(self) -> None:
        await self.target_chats.close_all()
        await self.scheduler.shutdown()
        await self.database.dispose()

    async def _mark_interrupted(self) -> None:
        repository = SqlRunRepository(self.database)
        await repository.mark_in_progress_interrupted()
        await self.target_chats.mark_interrupted()


def _proxy_public_url(settings: Settings) -> str:
    if settings.proxy.public_url:
        return settings.proxy.public_url.rstrip("/")
    host = settings.server.host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.server.port}/proxy"
