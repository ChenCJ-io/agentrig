"""Demo 2：OpenAI-compatible 被测 Agent + Evidence Judge。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from agentrig.agents.model_client import ModelOutput
from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.config import Settings
from agentrig.infrastructure.database import Database
from agentrig.profiles import ProfileCreate
from agentrig.targets import TargetCreate
from agentrig.targets.drivers import DriverRegistry, OpenAICompatibleDriver

from ._support import execute_one, print_result


class DemoJudgeModel:
    async def generate_json(self, **request: Any) -> ModelOutput:
        del request
        return ModelOutput(
            value={
                "verdict": "pass",
                "summary": "回答满足冻结的语义要求。",
                "criteria": [
                    {
                        "criterion": "回答明确说明采用 AgentRig V1",
                        "verdict": "pass",
                        "evidence_refs": [],
                    }
                ],
                "evidence_refs": [],
            },
            raw_text="{}",
            metadata={"model": "demo-judge"},
        )


async def run() -> None:
    def agent_endpoint(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "demo-agent",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "本次发布采用 AgentRig V1。",
                        }
                    }
                ],
                "usage": {"total_tokens": 12},
            },
        )

    drivers = DriverRegistry()
    drivers.register(
        "demo_openai",
        lambda: OpenAICompatibleDriver(
            transport=httpx.MockTransport(agent_endpoint),
        ),
    )
    services = ServiceContainer.build(
        Settings(target_network={"allowed_hosts": ["demo-agent.test"]}),
        database=Database("sqlite+aiosqlite:///:memory:"),
        drivers=drivers,
        model_client=DemoJudgeModel(),
    )
    os.environ["AGENTRIG_DEMO_JUDGE_KEY"] = "demo-only"
    await services.initialize()
    try:
        await services.cases.create(
            TestCaseCreate.model_validate(
                {
                    "id": "case_openai_judge",
                    "name": "OpenAI-compatible + Evidence Judge",
                    "supported_versions": ["demo-agent"],
                    "primary_evaluator": "evidence_judge",
                    "case_rubric": "回答必须明确说明本次发布采用 AgentRig V1。",
                    "turns": [
                        {
                            "position": 1,
                            "user_message": "本次发布采用什么评测方案？",
                        }
                    ],
                }
            )
        )
        await services.targets.create(
            TargetCreate.model_validate(
                {
                    "id": "target_openai_judge",
                    "name": "OpenAI-compatible Demo Agent",
                    "driver_type": "demo_openai",
                    "endpoint": "http://demo-agent.test/v1",
                    "versions": [{"version": "demo-agent"}],
                }
            )
        )
        await services.profiles.create(
            ProfileCreate.model_validate(
                {
                    "id": "profile_openai_judge",
                    "name": "Evidence Judge",
                    "config": {
                        "tool_mode": "controlled",
                        "provider_chain": [],
                        "primary_evaluator": "evidence_judge",
                        "judge_model": {
                            "base_url": "http://judge.test/v1",
                            "model": "demo-judge",
                            "secret_ref": "env:AGENTRIG_DEMO_JUDGE_KEY",
                        },
                    },
                }
            )
        )
        detail = await execute_one(
            services,
            case_id="case_openai_judge",
            target_id="target_openai_judge",
            profile_id="profile_openai_judge",
        )
        assert detail.evaluation_state == "pass"
        assert [item.evaluator_type.value for item in detail.evaluations] == [
            "evidence_judge"
        ]
        print_result("Demo 2 — OpenAI-compatible + Evidence Judge", detail)
    finally:
        await services.close()
        os.environ.pop("AGENTRIG_DEMO_JUDGE_KEY", None)


if __name__ == "__main__":
    asyncio.run(run())
