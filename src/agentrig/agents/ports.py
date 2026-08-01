"""V1 Core 对专业 Agent 的稳定端口。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ..evaluations.schemas import EvaluationDraft, EvaluationResult
from ..profiles.schemas import ModelConfigRef
from ..runs.schemas import CaseRunDetail
from .schemas import CuratorGeneration, CuratorInput


class AgentTaskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_run_id: str
    session_id: str | None = None
    plan_id: str | None = None
    tool_call_event_id: str | None = None


class SimulationCuratorPort(Protocol):
    async def generate(
        self,
        value: CuratorInput,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentTaskContext | None = None,
    ) -> CuratorGeneration: ...


class EvidenceJudgePort(Protocol):
    async def evaluate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
        context: AgentTaskContext | None = None,
    ) -> EvaluationDraft: ...


class AgentInvocationResultLinker(Protocol):
    async def attach_result_ref(
        self,
        invocation_id: str,
        result_ref: str,
    ) -> object: ...
