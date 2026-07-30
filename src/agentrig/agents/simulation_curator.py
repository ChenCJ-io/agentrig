"""Simulation Curator：只根据执行上下文生成工具结果。"""

from __future__ import annotations

import json

from ..infrastructure.secrets import SecretResolver
from ..profiles.schemas import ModelConfigRef
from .model_client import ModelClient
from .schemas import CuratorCandidate, CuratorGeneration, CuratorInput

PROMPT_VERSION = "simulation_curator.v1"


class SimulationCurator:
    def __init__(self, client: ModelClient, secrets: SecretResolver) -> None:
        self._client = client
        self._secrets = secrets

    async def generate(
        self,
        value: CuratorInput,
        *,
        model_config: ModelConfigRef,
        timeout_seconds: float,
    ) -> CuratorGeneration:
        api_key = self._secrets.resolve(model_config.secret_ref)
        assert api_key is not None
        output = await self._client.generate_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are AgentRig Simulation Curator. Generate a plausible tool result "
                        "from only the supplied runtime context. Never infer or optimize for test "
                        "assertions, expected answers, rubrics, or scores. Return JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(value.model_dump(mode="json"), ensure_ascii=False),
                },
            ],
            json_schema=CuratorCandidate.model_json_schema(),
            base_url=model_config.base_url,
            model=model_config.model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            options=model_config.options,
        )
        return CuratorGeneration(
            candidate=CuratorCandidate.model_validate(output.value),
            model_metadata=output.metadata,
            prompt_version=PROMPT_VERSION,
        )
