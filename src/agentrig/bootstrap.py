"""AgentRig V1 Core 与 V2 协作适配器的唯一装配点。"""

from __future__ import annotations

from dataclasses import dataclass

from .agents import (
    EvidenceJudge,
    ModelClient,
    OpenAICompatibleModelClient,
    SimulationCurator,
)
from .agents.invocation_coordinator import (
    AgentInvocationCoordinator,
    UnavailableAgentTaskTransport,
)
from .agents.invocation_service import AgentInvocationService
from .agents.ports import EvidenceJudgePort, SimulationCuratorPort
from .assistant import AssistantService, EvaluationPlanService
from .assistant.run_notifier import AssistantRunNotifier
from .cases import CaseService
from .config import Settings, get_settings
from .evaluations.rule_evaluator import RuleEvaluator
from .evaluations.service import EvaluationService
from .infrastructure.database import Database
from .infrastructure.database.repositories import (
    SqlAgentInvocationRepository,
    SqlAssistantRepository,
    SqlCaseRepository,
    SqlEvaluationRepository,
    SqlProfileRepository,
    SqlRunRepository,
    SqlSampleRepository,
    SqlTargetRepository,
    SqlToolCallEvidenceReader,
)
from .infrastructure.secrets import SecretResolver
from .integrations.agentteams import (
    AgentTeamsBridge,
    AgentTeamsEvidenceJudge,
    AgentTeamsSimulationCurator,
    MatrixAgentTaskTransport,
    MatrixClient,
)
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
    assistant: AssistantService
    evaluation_plans: EvaluationPlanService
    agent_invocations: AgentInvocationService
    agentteams_bridge: AgentTeamsBridge
    runs: RunService
    scheduler: RunScheduler
    drivers: DriverRegistry
    proxy_scopes: ProxyScopeRegistry
    backend_registry: BackendRegistry
    server_api_token: str | None
    role_mcp_tokens: dict[str, str | None]

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
        role_mcp_tokens = {
            "manager": secret_resolver.resolve(
                resolved_settings.agentteams.manager_mcp_token_ref
            ),
            "curator": secret_resolver.resolve(
                resolved_settings.agentteams.curator_mcp_token_ref
            ),
            "judge": secret_resolver.resolve(
                resolved_settings.agentteams.judge_mcp_token_ref
            ),
        }
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
        invocation_repository = SqlAgentInvocationRepository(resolved_database)

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
        assistant = AssistantService(assistant_repository)
        redactor = Redactor(
            sensitive_keys=resolved_settings.evidence.sensitive_keys,
            sensitive_paths=resolved_settings.evidence.sensitive_paths,
        )
        agent_invocations = AgentInvocationService(
            invocation_repository,
            assistant_repository=assistant_repository,
            redactor=redactor,
        )
        matrix_config = resolved_settings.agentteams.matrix
        matrix_token = (
            secret_resolver.resolve(matrix_config.access_token_ref)
            if resolved_settings.agentteams.enabled
            and matrix_config.access_token_ref is not None
            else None
        )
        matrix_client = (
            MatrixClient(
                matrix_config.homeserver_url,
                matrix_token,
                timeout_seconds=matrix_config.request_timeout_seconds,
            )
            if matrix_config.homeserver_url and matrix_token
            else None
        )
        agentteams_bridge = AgentTeamsBridge(
            enabled=resolved_settings.agentteams.enabled,
            assistant=assistant,
            repository=assistant_repository,
            invocations=agent_invocations,
            client=matrix_client,
            bridge_user_id=matrix_config.bridge_user_id,
            manager_user_id=matrix_config.manager_user_id,
            curator_user_id=matrix_config.curator_user_id,
            judge_user_id=matrix_config.judge_user_id,
            runtime_health_url=resolved_settings.agentteams.health_url,
            role_mcp_configured=all(role_mcp_tokens.values()),
        )
        simulation_curator: SimulationCuratorPort = SimulationCurator(
            resolved_model_client,
            secret_resolver,
        )
        evidence_judge: EvidenceJudgePort = EvidenceJudge(
            resolved_model_client,
            secret_resolver,
        )
        if resolved_settings.agentteams.enabled:
            transport = (
                MatrixAgentTaskTransport(
                    matrix_client,
                    curator_user_id=matrix_config.curator_user_id,
                    judge_user_id=matrix_config.judge_user_id,
                    default_room_id=matrix_config.default_worker_room_id,
                )
                if matrix_client is not None
                else UnavailableAgentTaskTransport(
                    "AgentTeams is enabled but Matrix is not fully configured"
                )
            )
            coordinator = AgentInvocationCoordinator(agent_invocations, transport)
            simulation_curator = AgentTeamsSimulationCurator(coordinator)
            evidence_judge = AgentTeamsEvidenceJudge(coordinator)
        recorder = EventRecorder(
            run_repository,
            redactor,
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
            simulation_curator=simulation_curator,
            evidence_judge=evidence_judge,
            invocation_results=agent_invocations,
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
        evaluation_plans = EvaluationPlanService(
            repository=assistant_repository,
            assistant=assistant,
            runs=runs,
        )
        scheduler.add_completion_listener(
            AssistantRunNotifier(
                repository=assistant_repository,
                assistant=assistant,
                bridge=agentteams_bridge,
            )
        )
        return cls(
            settings=resolved_settings,
            database=resolved_database,
            cases=cases,
            targets=targets,
            profiles=profiles,
            samples=samples,
            assistant=assistant,
            evaluation_plans=evaluation_plans,
            agent_invocations=agent_invocations,
            agentteams_bridge=agentteams_bridge,
            runs=runs,
            scheduler=scheduler,
            drivers=driver_registry,
            proxy_scopes=proxy_scopes,
            backend_registry=resolved_backend_registry,
            server_api_token=server_api_token,
            role_mcp_tokens=role_mcp_tokens,
        )

    async def initialize(self) -> None:
        await self.database.create_schema()
        await self._mark_interrupted()
        await self.agentteams_bridge.start()

    async def close(self) -> None:
        await self.agentteams_bridge.close()
        await self.scheduler.shutdown()
        await self.database.dispose()

    async def _mark_interrupted(self) -> None:
        repository = SqlRunRepository(self.database)
        await repository.mark_in_progress_interrupted()
        await self.agent_invocations.cancel_in_progress()


def _proxy_public_url(settings: Settings) -> str:
    if settings.proxy.public_url:
        return settings.proxy.public_url.rstrip("/")
    host = settings.server.host
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.server.port}/proxy"
