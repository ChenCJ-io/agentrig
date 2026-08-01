"""AgentTeams Worker 调用的角色和生命周期。"""

from enum import StrEnum


class AgentRole(StrEnum):
    SIMULATION_CURATOR = "simulation_curator"
    EVIDENCE_JUDGE = "evidence_judge"


class AgentInvocationStatus(StrEnum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            AgentInvocationStatus.COMPLETED,
            AgentInvocationStatus.FAILED,
            AgentInvocationStatus.TIMED_OUT,
            AgentInvocationStatus.CANCELLED,
        }
