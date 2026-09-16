"""确定性评判与落库前脱敏。"""

from __future__ import annotations

from datetime import datetime, timezone

from agentrig.evaluations.rule_evaluator import RuleEvaluator
from agentrig.runs.models import RunEventType
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import RunEvent


def event(seq: int, event_type: RunEventType, payload: dict[str, object]) -> RunEvent:
    return RunEvent(
        id=f"evt_{seq}",
        case_run_id="case_run_1",
        seq=seq,
        event_type=event_type,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )


def test_rule_evaluator_supports_order_arguments_text_and_no_error() -> None:
    events = [
        event(
            1,
            RunEventType.TOOL_CALL,
            {"turn_position": 1, "tool_name": "search", "arguments": {"q": "x", "limit": 5}},
        ),
        event(
            2,
            RunEventType.TOOL_CALL,
            {"turn_position": 1, "tool_name": "read", "arguments": {"id": 1}},
        ),
        event(
            3,
            RunEventType.ASSISTANT_MESSAGE,
            {"turn_position": 1, "text": "found result"},
        ),
    ]
    result = RuleEvaluator().evaluate(
        {
            "case_assertions": [
                {"kind": "first_action", "expected_action": "tool"},
                {"kind": "tool_call_order", "tool_names": ["search", "read"]},
                {
                    "kind": "tool_arguments_equal",
                    "tool_name": "search",
                    "expected_arguments": {"q": "x", "limit": 5},
                },
                {"kind": "text_regex", "value": "found.+result"},
                {"kind": "no_execution_error"},
            ],
            "turns": [],
        },
        events,
    )
    assert result.verdict == "pass"
    assert len(result.criteria) == 5


def test_rule_argument_equality_is_exact_and_refusal_is_a_first_action() -> None:
    result = RuleEvaluator().evaluate(
        {
            "case_assertions": [
                {
                    "kind": "tool_arguments_equal",
                    "tool_name": "search",
                    "expected_arguments": {"q": "x"},
                },
                {"kind": "first_action", "expected_action": "refuse"},
            ],
            "turns": [],
        },
        [
            event(
                1,
                RunEventType.TOOL_CALL,
                {
                    "turn_position": 1,
                    "tool_name": "search",
                    "arguments": {"q": "x", "limit": 5},
                },
            ),
            event(
                2,
                RunEventType.ASSISTANT_MESSAGE,
                {
                    "turn_position": 1,
                    "text": "I cannot do that.",
                    "refusal": True,
                    "first_action": "refuse",
                },
            ),
        ],
    )
    assert result.verdict == "fail"
    assert [item.verdict for item in result.criteria] == ["fail", "pass"]


def test_redactor_masks_default_keys_and_configured_paths_without_raw_copy() -> None:
    payload = {
        "authorization": "Bearer real",
        "nested": {
            "access_token": "real-token",
            "safe": "visible",
            "customer": {"phone": "123"},
        },
    }
    redacted = Redactor(sensitive_paths=["nested.customer.phone"]).redact(payload)
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["nested"]["access_token"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "visible"
    assert redacted["nested"]["customer"]["phone"] == "[REDACTED]"
    assert payload["authorization"] == "Bearer real"
