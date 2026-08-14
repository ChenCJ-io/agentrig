"""AgentTeams Matrix 协作与 Worker 任务适配。"""

from .adapters import AgentTeamsEvidenceJudge, AgentTeamsSimulationCurator
from .bridge import AgentTeamsBridge, AgentTeamsHealth
from .compat import (
    AgentTeams122Adapter,
    AgentTeamsCapabilityReport,
    AgentTeamsInvocationEvidence,
    AgentTeamsMembershipEvidence,
    AgentTeamsObservation,
    AgentTeamsProfileManifest,
    AgentTeamsSkillEvidence,
    LegacyAgentTeams112Adapter,
    adapter_for,
)
from .matrix_client import MatrixClient
from .transport import MatrixAgentTaskTransport

__all__ = [
    "AgentTeamsBridge",
    "AgentTeams122Adapter",
    "AgentTeamsCapabilityReport",
    "AgentTeamsEvidenceJudge",
    "AgentTeamsHealth",
    "AgentTeamsInvocationEvidence",
    "AgentTeamsMembershipEvidence",
    "AgentTeamsObservation",
    "AgentTeamsProfileManifest",
    "AgentTeamsSkillEvidence",
    "AgentTeamsSimulationCurator",
    "MatrixAgentTaskTransport",
    "MatrixClient",
    "LegacyAgentTeams112Adapter",
    "adapter_for",
]
