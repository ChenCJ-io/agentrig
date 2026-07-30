"""V1 对外数据契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentrig.cases.schemas import Assertion, TestCaseCreate
from agentrig.profiles.schemas import ExecutionProfileConfig
from agentrig.runs.schemas import RunCasesRequest
from agentrig.targets.schemas import TargetCreate
from agentrig.tool_results import SampleCreate


def test_case_supports_multiturn_fixtures_and_opaque_versions() -> None:
    case = TestCaseCreate.model_validate(
        {
            "name": "multi turn",
            "supported_versions": ["git:a84c120", "feature/search-v2"],
            "primary_evaluator": "external_controller",
            "turns": [
                {
                    "position": 1,
                    "user_message": "create it",
                    "fixtures": [
                        {
                            "tool_name": "create_order",
                            "match_arguments": {"sku": "A"},
                            "result": {"id": "O-1"},
                        }
                    ],
                },
                {"position": 2, "user_message": "query it"},
            ],
        }
    )
    assert len(case.turns) == 2
    assert case.supported_versions == ["git:a84c120", "feature/search-v2"]


def test_case_turn_positions_must_be_contiguous() -> None:
    with pytest.raises(ValidationError, match="contiguous"):
        TestCaseCreate.model_validate(
            {
                "name": "invalid",
                "primary_evaluator": "external_controller",
                "turns": [{"position": 2, "user_message": "hello"}],
            }
        )


def test_assertions_reject_unknown_fields_and_invalid_regex() -> None:
    with pytest.raises(ValidationError):
        Assertion.model_validate({"kind": "python", "value": "danger()"})
    with pytest.raises(ValidationError, match="invalid text_regex"):
        Assertion(kind="text_regex", value="[")


def test_run_cases_requires_one_selection_source_and_one_or_two_targets() -> None:
    target = {
        "role": "candidate",
        "inline_target": {
            "name": "echo",
            "driver_type": "http_sse",
            "endpoint": "http://localhost:9000",
        },
    }
    request = RunCasesRequest(case_ids=["case_1"], targets=[target])
    assert request.case_ids == ["case_1"]
    with pytest.raises(ValidationError, match="exactly one"):
        RunCasesRequest(
            case_ids=["case_1"],
            selector={},
            targets=[target],
        )


def test_ab_requires_baseline_and_candidate() -> None:
    inline = {
        "name": "echo",
        "driver_type": "http_sse",
        "endpoint": "http://localhost:9000",
    }
    request = RunCasesRequest(
        case_ids=["case_1"],
        targets=[
            {"role": "baseline", "inline_target": inline},
            {"role": "candidate", "inline_target": inline},
        ],
    )
    assert {target.role for target in request.targets} == {"baseline", "candidate"}


def test_secret_ref_must_be_environment_reference() -> None:
    with pytest.raises(ValidationError, match="env:"):
        TargetCreate(name="unsafe", driver_type="http_sse", secret_ref="plain-secret")


def test_arbitrary_json_fields_cannot_hide_plaintext_credentials() -> None:
    with pytest.raises(ValidationError, match="secret_ref"):
        TargetCreate(
            name="unsafe",
            driver_type="http_sse",
            options={"request_headers": {"Authorization": "Bearer secret"}},
        )
    with pytest.raises(ValidationError, match="secret_ref"):
        ExecutionProfileConfig(
            curator_model={
                "base_url": "http://model.test",
                "model": "x",
                "secret_ref": "env:MODEL_KEY",
                "options": {"api_key": "plaintext"},
            }
        )
    with pytest.raises(ValidationError, match="secret_ref"):
        TestCaseCreate(
            name="unsafe state",
            initial_state={"access_token": "plaintext"},
            turns=[{"position": 1, "user_message": "hello"}],
        )
    with pytest.raises(ValidationError, match="secret_ref"):
        SampleCreate(
            name="unsafe sample",
            tool_name="login",
            content={"token": "plaintext"},
        )
