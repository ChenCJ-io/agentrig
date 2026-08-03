"""Simulation Curator：只根据执行上下文生成工具结果。"""

from __future__ import annotations

import json

from ..infrastructure.secrets import SecretResolver
from ..profiles.schemas import ModelConfigRef
from .model_client import ModelClient
from .ports import AgentTaskContext
from .schemas import CuratorCandidate, CuratorGeneration, CuratorInput

PROMPT_VERSION = "simulation_curator.v2"


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
        context: AgentTaskContext | None = None,
    ) -> CuratorGeneration:
        del context
        api_key = self._secrets.resolve(model_config.secret_ref)
        assert api_key is not None
        output = await self._client.generate_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are AgentRig Simulation Curator. Generate a plausible tool result "
                        "from only the supplied runtime context. Never infer or optimize for test "
                        "assertions, expected answers, rubrics, or scores. Return JSON only. "
                        "Prefer an object with exactly two fields: result (the tool payload) and "
                        "state_updates (an object, usually empty)."
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
        candidate_value = output.value
        # Some OpenAI-compatible providers support JSON text but not json_schema and
        # naturally return the tool payload itself. The Provider still validates this
        # payload against the ToolCall result schema before it can be injected.
        if (
            model_config.options.get("structured_output", True) is False
            and isinstance(candidate_value, dict)
            and "result" not in candidate_value
        ):
            candidate_value = {"result": candidate_value, "state_updates": {}}
        return CuratorGeneration(
            candidate=CuratorCandidate.model_validate(candidate_value),
            model_metadata=output.metadata,
            prompt_version=PROMPT_VERSION,
        )
