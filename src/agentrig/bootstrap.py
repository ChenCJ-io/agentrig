"""AgentRig V1 模块化单体的唯一装配点。"""

from __future__ import annotations

from dataclasses import dataclass

from .agents import (
    EvidenceJudge,
    ModelClient,
    OpenAICompatibleModelClient,
    SimulationCurator,
)
from .cases import CaseService
from .config import Settings, get_settings
from .evaluations.rule_evaluator import RuleEvaluator
from .evaluations.service import EvaluationService
from .infrastructure.database import Database
from .infrastructure.database.repositories import (
    SqlCaseRepository,
    SqlEvaluationRepository,
    SqlProfileRepository,
    SqlRunRepository,
    SqlSampleRepository,
    SqlTargetRepository,
    SqlToolCallEvidenceReader,
)
from .infrastructure.secrets import SecretResolver
from .profiles import ProfileService
from .profiles.resolver import ProfileResolver
from .proxy.backend import BackendRegistry
from .proxy.scoped import ProxyScopeRegistry
from .runs.event_recorder import EventRecorder
from .runs.executor import CaseExecutor
from .runs.planner import RunPlanner
from .runs.redactor import Redactor
from .runs.scheduler import RunScheduler
from .runs.service import RunService
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
    samples: SampleService
    runs: RunService
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
    ) -> ServiceContainer:
        resolved_settings = settings or get_settings()
        resolved_database = database or Database(resolved_settings.database.url)
        driver_registry = drivers or DriverRegistry(
            python_allowlist=resolved_settings.execution.python_driver_allowlist,
            subprocess_allowlist=resolved_settings.execution.subprocess_allowlist,
        )
        resolved_model_client = model_client or OpenAICompatibleModelClient()
        secret_resolver = SecretResolver()
        server_api_token = secret_resolver.resolve(
            resolved_settings.server.api_token_ref
        )
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

        cases = CaseService(case_repository)
        targets = TargetService(
            target_repository,
            drivers=driver_registry,
            secrets=secret_resolver,
        )
        profiles = ProfileService(profile_repository)
        samples = SampleService(
            sample_repository,
            evidence_reader=SqlToolCallEvidenceReader(resolved_database),
        )
        recorder = EventRecorder(
            run_repository,
            Redactor(
                sensitive_keys=resolved_settings.evidence.sensitive_keys,
                sensitive_paths=resolved_settings.evidence.sensitive_paths,
            ),
        )
        executor = CaseExecutor(
            runs=run_repository,
            evaluations=evaluation_repository,
            samples=sample_repository,
            drivers=driver_registry,
            secrets=secret_resolver,
            recorder=recorder,
            validator=ToolResultValidator(
                max_bytes=resolved_settings.evidence.max_event_payload_bytes,
            ),
            simulation_curator=SimulationCurator(
                resolved_model_client,
                secret_resolver,
            ),
            evidence_judge=EvidenceJudge(
                resolved_model_client,
                secret_resolver,
            ),
            real_tool_client=resolved_real_tool_client,
            real_tool_allowlist=resolved_settings.execution.real_tool_allowlist,
            rule_evaluator=RuleEvaluator(),
            proxy_scopes=proxy_scopes,
            proxy_public_url=_proxy_public_url(resolved_settings),
            server_api_token=server_api_token,
        )
        scheduler = RunScheduler(run_repository, executor)
        planner = RunPlanner(
            cases=cases,
            targets=targets,
            profiles=profiles,
            profile_resolver=ProfileResolver(resolved_settings),
            drivers=driver_registry,
            runs=run_repository,
        )
        runs = RunService(
            planner=planner,
            scheduler=scheduler,
            repository=run_repository,
            evaluations=EvaluationService(
                evaluation_repository,
                run_repository,
            ),
        )
        return cls(
            settings=resolved_settings,
            database=resolved_database,
            cases=cases,
            targets=targets,
            profiles=profiles,
            samples=samples,
            runs=runs,
            scheduler=scheduler,
            drivers=driver_registry,
            proxy_scopes=proxy_scopes,
            backend_registry=resolved_backend_registry,
            server_api_token=server_api_token,
        )

    async def initialize(self) -> None:
        await self.database.create_schema()
        await self._mark_interrupted()

    async def close(self) -> None:
        await self.scheduler.shutdown()
        await self.database.dispose()

    async def _mark_interrupted(self) -> None:
        repository = SqlRunRepository(self.database)
        await repository.mark_in_progress_interrupted()


def _proxy_public_url(settings: Settings) -> str:
    if settings.proxy.public_url:
        return settings.proxy.public_url.rstrip("/")
    host = settings.server.host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.server.port}/proxy"
