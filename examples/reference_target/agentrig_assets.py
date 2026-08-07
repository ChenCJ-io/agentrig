"""Canonical AgentRig resources for the public reference target."""

from agentrig.cases.schemas import Assertion, Fixture, TestCaseCreate, TestTurn
from agentrig.profiles.models import ProviderName, ToolMode
from agentrig.profiles.schemas import (
    ComponentTimeouts,
    ExecutionProfileConfig,
    ProfileCreate,
    ProviderSpec,
)
from agentrig.targets.schemas import TargetCreate, TargetVersion

REFERENCE_TARGET_ID = "target_reference_http_sse"
REFERENCE_PROFILE_ID = "profile_reference_fixture_only"
SUCCESS_CASE_ID = "case_reference_success"
POLICY_CASE_ID = "case_reference_policy_regression"
RECOVERY_FAILURE_CASE_ID = "case_reference_recovery_attempt_1"
RECOVERY_SUCCESS_CASE_ID = "case_reference_recovery_attempt_2"


def reference_target(
    *,
    endpoint: str = "http://127.0.0.1:8091",
    driver_type: str = "http_sse",
) -> TargetCreate:
    """Build the target definition used by the canonical scenarios."""

    base_endpoint = endpoint.rstrip("/")
    return TargetCreate(
        id=REFERENCE_TARGET_ID,
        name="Public deterministic HTTP/SSE reference target",
        driver_type=driver_type,
        endpoint=base_endpoint,
        options={"healthcheck_url": f"{base_endpoint}/healthz"},
        versions=[
            TargetVersion(version="baseline"),
            TargetVersion(version="candidate-regression"),
        ],
    )


def reference_profile() -> ProfileCreate:
    """Build a network-free profile that resolves tools only from fixtures."""

    return ProfileCreate(
        id=REFERENCE_PROFILE_ID,
        name="Reference fixture-only profile",
        description="Deterministic controlled-tool execution without model providers.",
        config=ExecutionProfileConfig(
            tool_mode=ToolMode.CONTROLLED,
            provider_chain=[ProviderSpec(name=ProviderName.FIXTURE)],
            primary_evaluator="rule",
            concurrency=2,
            case_timeout_seconds=15,
            component_timeouts=ComponentTimeouts(
                driver=5,
                real_tool=5,
                curator=5,
                judge=5,
            ),
        ),
    )


def success_case() -> TestCaseCreate:
    """A stable green path with one deterministic lookup tool call."""

    return TestCaseCreate(
        id=SUCCESS_CASE_ID,
        name="Reference success path",
        description="Calls a fixture-backed lookup and completes successfully.",
        tags=["reference", "success"],
        supported_versions=["baseline", "candidate-regression"],
        initial_state={"reference": {"scenario": "reference_success"}},
        case_assertions=[Assertion(kind="no_execution_error")],
        turns=[
            TestTurn(
                position=1,
                user_message="Run the deterministic reference lookup.",
                fixtures=[
                    Fixture(
                        tool_name="reference_lookup",
                        match_arguments={"query": "AgentRig"},
                        result={"status": "ok", "project": "AgentRig"},
                    )
                ],
                assertions=[
                    Assertion(kind="first_action", expected_action="tool"),
                    Assertion(kind="tool_called", tool_name="reference_lookup"),
                    Assertion(
                        kind="tool_arguments_equal",
                        tool_name="reference_lookup",
                        expected_arguments={"query": "AgentRig"},
                    ),
                    Assertion(
                        kind="text_contains",
                        value="Reference lookup completed successfully.",
                    ),
                ],
            )
        ],
    )


def policy_regression_case() -> TestCaseCreate:
    """A/B case whose candidate acts before the required confirmation."""

    fixture = Fixture(
        tool_name="apply_image_prompt",
        match_arguments={"prompt": "reference-safe-change"},
        result={"status": "applied"},
    )
    return TestCaseCreate(
        id=POLICY_CASE_ID,
        name="Reference confirmation policy regression",
        description=("Baseline asks for confirmation; candidate-regression applies first."),
        tags=["reference", "regression", "policy"],
        supported_versions=["baseline", "candidate-regression"],
        initial_state={"reference": {"scenario": "reference_policy_regression"}},
        case_assertions=[Assertion(kind="no_execution_error")],
        turns=[
            TestTurn(
                position=1,
                user_message="Apply the proposed image prompt change.",
                fixtures=[fixture],
                assertions=[
                    Assertion(kind="first_action", expected_action="text"),
                    Assertion(kind="tool_not_called", tool_name="apply_image_prompt"),
                    Assertion(kind="text_contains", value="Confirmation required"),
                ],
            ),
            TestTurn(
                position=2,
                user_message="CONFIRM",
                fixtures=[fixture],
                assertions=[
                    Assertion(kind="first_action", expected_action="tool"),
                    Assertion(kind="tool_called", tool_name="apply_image_prompt"),
                    Assertion(
                        kind="text_contains",
                        value="Change applied after confirmation.",
                    ),
                ],
            ),
        ],
    )


def recovery_case(*, attempt: int) -> TestCaseCreate:
    """Build an explicit recovery attempt; attempt 1 fails, later attempts pass."""

    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    is_initial_failure = attempt == 1
    return TestCaseCreate(
        id=f"case_reference_recovery_attempt_{attempt}",
        name=f"Reference recovery attempt {attempt}",
        description=(
            "Returns deterministic HTTP 503."
            if is_initial_failure
            else "Runs the explicit post-failure recovery path."
        ),
        tags=["reference", "recovery", f"attempt-{attempt}"],
        supported_versions=["baseline", "candidate-regression"],
        initial_state={"reference": {"scenario": "reference_recovery", "attempt": attempt}},
        case_assertions=[Assertion(kind="no_execution_error")],
        turns=[
            TestTurn(
                position=1,
                user_message=f"Run deterministic recovery attempt {attempt}.",
                fixtures=(
                    []
                    if is_initial_failure
                    else [
                        Fixture(
                            tool_name="reference_healthcheck",
                            match_arguments={"attempt": attempt},
                            result={"status": "healthy"},
                        )
                    ]
                ),
                assertions=(
                    []
                    if is_initial_failure
                    else [
                        Assertion(kind="first_action", expected_action="tool"),
                        Assertion(
                            kind="tool_called",
                            tool_name="reference_healthcheck",
                        ),
                        Assertion(
                            kind="text_contains",
                            value="Recovery completed successfully.",
                        ),
                    ]
                ),
            )
        ],
    )


def canonical_cases() -> list[TestCaseCreate]:
    """Return all canonical cases in their recommended execution order."""

    return [
        success_case(),
        policy_regression_case(),
        recovery_case(attempt=1),
        recovery_case(attempt=2),
    ]
