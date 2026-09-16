"""V1 Core 对专业 Agent 的稳定端口。"""

from __future__ import annotations

from typing import Protocol

from ..evaluations.schemas import EvaluationDraft, EvaluationResult
from ..profiles.schemas import ModelConfigRef
from ..runs.schemas import CaseRunDetail
from .schemas import CuratorGeneration, CuratorInput


class SimulationCuratorPort(Protocol):
    async def generate(
        self,
        value: CuratorInput,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
    ) -> CuratorGeneration: ...


class EvidenceJudgePort(Protocol):
    async def evaluate(
        self,
        detail: CaseRunDetail,
        *,
        rule_result: EvaluationResult | None,
        model_config: ModelConfigRef,
        timeout_seconds: float,
    ) -> EvaluationDraft: ...
