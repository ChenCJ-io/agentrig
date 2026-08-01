"""Idempotently seed the local lassist + AgentTeams acceptance assets."""

from __future__ import annotations

import asyncio

from agentrig.bootstrap import ServiceContainer
from agentrig.cases import TestCaseCreate
from agentrig.cases.models import ReviewStatus
from agentrig.cases.schemas import TestCasePatch
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.profiles import ProfileCreate
from agentrig.profiles.schemas import ProfilePatch
from agentrig.targets import TargetCreate
from agentrig.targets.schemas import TargetPatch

TARGET_ID = "target_lassist_local"
PROFILE_ID = "profile_lassist_agentteams"
CASE_ID = "case_lassist_three_agent_demo"


def target_value() -> TargetCreate:
    device_info = {
        "device_id": "AGENTRIG-LOCAL-DEMO",
        "os": "macOS",
        "os_version": "local",
        "app_version": "9.2.0",
        "tool_version": 4,
        "tool_version_branch": None,
        "app_build": "65",
    }
    return TargetCreate(
        id=TARGET_ID,
        name="本机 lassist / Pixcake Agent",
        driver_type="pixcake_http_sse",
        endpoint="http://127.0.0.1:8000",
        options={
            "user_id": 1045931,
            "device_info": device_info,
            "chat_channel": "pixcake_client",
            "healthcheck_url": "http://127.0.0.1:8000/health",
        },
        versions=[
            {
                "version": "9.2.0",
                "options": {
                    "device_info": {
                        "app_version": "9.2.0",
                        "tool_version": 4,
                    }
                },
            }
        ],
    )


def profile_value() -> ProfileCreate:
    model = {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "secret_ref": "env:DEEPSEEK_API_KEY",
    }
    return ProfileCreate(
        id=PROFILE_ID,
        name="lassist · AgentTeams 三角色评测",
        description=(
            "Manager 规划并提交；Simulation Curator 模拟 Pixcake 工具结果；"
            "Evidence Judge 基于完整证据裁决。"
        ),
        config={
            "tool_mode": "controlled",
            "provider_chain": [{"name": "simulation_curator"}],
            "primary_evaluator": "evidence_judge",
            "concurrency": 1,
            "case_timeout_seconds": 600,
            "component_timeouts": {
                "driver": 180,
                "real_tool": 60,
                "curator": 180,
                "judge": 180,
            },
            "repeat_count": 1,
            "curator_model": model,
            "judge_model": model,
        },
    )


def case_value() -> TestCaseCreate:
    return TestCaseCreate(
        id=CASE_ID,
        name="背景增强：lassist 三 Agent 全链路",
        description=(
            "真实调用本机 lassist；apply_image_prompt 的工具结果由独立 Curator "
            "按冻结输入生成，最终由独立 Judge 基于运行证据裁决。"
        ),
        tags=["local-demo", "lassist", "agentteams", "pixcake"],
        supported_versions=["9.2.0"],
        primary_evaluator="evidence_judge",
        initial_state={
            "pixcake_request": {
                "attachments": [
                    {
                        "type": "image",
                        "image_id": "1",
                        "file_path": "seed://scene_bg.jpg",
                    }
                ],
                "metadata": {"project_id": "1698494"},
            }
        },
        case_assertions=[{"kind": "no_execution_error"}],
        case_rubric=(
            "被测 Agent 应完成用户的背景增强意图，且结论必须能由本次运行事件直接支持；"
            "不得因模拟工具返回成功而忽略调用参数或后续回复中的明显错误。"
        ),
        turns=[
            {
                "position": 1,
                "user_message": "把背景增强一下，层次感好一点",
                "simulation_instruction": (
                    "这是本地受控演示。若参数符合工具 schema，返回一次成功编辑结果："
                    "image_id=1、success=true、record_id=1；不要调用真实外部工具。"
                ),
                "assertions": [
                    {"kind": "tool_called", "tool_name": "apply_image_prompt"},
                    {"kind": "no_execution_error"},
                ],
                "rubric": (
                    "应理解为对当前图片背景进行增强，调用合适的图像编辑工具，并在工具"
                    "成功后给出简洁、明确且不夸大的完成反馈。"
                ),
            }
        ],
    )


async def upsert_assets() -> None:
    services = ServiceContainer.build()
    await services.initialize()
    try:
        target = target_value()
        try:
            await services.targets.get(TARGET_ID)
        except AgentRigError as exc:
            if exc.detail.code is not ErrorCode.NOT_FOUND:
                raise
            await services.targets.create(target)
        else:
            await services.targets.update(
                TARGET_ID,
                TargetPatch.model_validate(
                    target.model_dump(exclude={"id"}, mode="json")
                ),
            )

        profile = profile_value()
        try:
            await services.profiles.get(PROFILE_ID)
        except AgentRigError as exc:
            if exc.detail.code is not ErrorCode.NOT_FOUND:
                raise
            await services.profiles.create(profile)
        else:
            await services.profiles.update(
                PROFILE_ID,
                ProfilePatch.model_validate(
                    profile.model_dump(exclude={"id"}, mode="json")
                ),
            )

        case = case_value()
        try:
            current_case = await services.cases.get(CASE_ID)
        except AgentRigError as exc:
            if exc.detail.code is not ErrorCode.NOT_FOUND:
                raise
            await services.cases.create(case)
            await services.cases.review(CASE_ID, ReviewStatus.APPROVED)
        else:
            if current_case.review_status is not ReviewStatus.APPROVED:
                await services.cases.update(
                    CASE_ID,
                    TestCasePatch.model_validate(
                        case.model_dump(exclude={"id"}, mode="json")
                    ),
                )
                await services.cases.review(CASE_ID, ReviewStatus.APPROVED)

        check = await services.targets.check(TARGET_ID, version="9.2.0")
        if not check.reachable:
            raise RuntimeError(f"lassist target check failed: {check.message}")
        print(f"target={TARGET_ID}")
        print(f"profile={PROFILE_ID}")
        print(f"case={CASE_ID}")
        print(f"target_check={check.message}")
    finally:
        await services.close()


if __name__ == "__main__":
    asyncio.run(upsert_assets())
