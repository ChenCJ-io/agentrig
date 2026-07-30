"""V1 的有限、确定性 Rule Evaluator。"""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator

from ..cases.schemas import Assertion
from ..runs.models import RunEventType
from ..runs.schemas import RunEvent
from .schemas import EvaluationCriterion, EvaluationDraft


class RuleEvaluator:
    def evaluate(
        self,
        case_snapshot: dict[str, Any],
        events: list[RunEvent],
    ) -> EvaluationDraft:
        scoped_assertions: list[Assertion] = [
            Assertion.model_validate(item)
            for item in case_snapshot.get("case_assertions", [])
        ]
        for turn in case_snapshot.get("turns", []):
            for item in turn.get("assertions", []):
                assertion = Assertion.model_validate(item)
                if assertion.turn_position is None:
                    assertion = assertion.model_copy(
                        update={"turn_position": int(turn["position"])}
                    )
                scoped_assertions.append(assertion)

        criteria = [
            self._evaluate_assertion(assertion, self._scope(events, assertion.turn_position))
            for assertion in scoped_assertions
        ]
        passed = all(item.verdict == "pass" for item in criteria)
        evidence_refs = list(
            dict.fromkeys(ref for item in criteria for ref in item.evidence_refs)
        )
        pass_count = sum(item.verdict == "pass" for item in criteria)
        return EvaluationDraft(
            verdict="pass" if passed else "fail",
            summary=f"{pass_count}/{len(criteria)} rule assertions passed",
            criteria=criteria,
            evidence_refs=evidence_refs,
            config_snapshot={"assertions": [item.model_dump(mode="json") for item in scoped_assertions]},
        )

    @staticmethod
    def _scope(events: list[RunEvent], turn_position: int | None) -> list[RunEvent]:
        if turn_position is None:
            return events
        return [
            event
            for event in events
            if event.payload.get("turn_position") == turn_position
        ]

    def _evaluate_assertion(
        self,
        assertion: Assertion,
        events: list[RunEvent],
    ) -> EvaluationCriterion:
        tool_calls = [
            event for event in events if event.event_type is RunEventType.TOOL_CALL
        ]
        messages = [
            event for event in events if event.event_type is RunEventType.ASSISTANT_MESSAGE
        ]
        text_segments = [
            event for event in events if event.event_type is RunEventType.ASSISTANT_TEXT
        ]
        errors = [event for event in events if event.event_type is RunEventType.ERROR]
        verdict = False
        refs: list[str] = []
        description = self._description(assertion)

        if assertion.kind == "first_action":
            declared = next(
                (
                    str(message.payload["first_action"])
                    for message in messages
                    if message.payload.get("first_action") in {"tool", "text", "refuse"}
                ),
                None,
            )
            if declared is not None:
                action = declared
                reference = (
                    tool_calls[0]
                    if action == "tool" and tool_calls
                    else text_segments[0]
                    if text_segments
                    else messages[0]
                    if messages
                    else None
                )
                refs = [reference.id] if reference is not None else []
                verdict = action == assertion.expected_action
            else:
                candidates = sorted(
                    [*tool_calls, *text_segments, *messages],
                    key=lambda event: event.seq,
                )
                first = candidates[0] if candidates else None
                if first is not None:
                    refs = [first.id]
                    action = (
                        "tool"
                        if first.event_type is RunEventType.TOOL_CALL
                        else "refuse"
                        if first.payload.get("refusal") is True
                        else "text"
                    )
                    verdict = action == assertion.expected_action
        elif assertion.kind == "tool_called":
            matched = [
                event for event in tool_calls if event.payload.get("tool_name") == assertion.tool_name
            ]
            verdict = bool(matched)
            refs = [event.id for event in matched]
        elif assertion.kind == "tool_not_called":
            matched = [
                event for event in tool_calls if event.payload.get("tool_name") == assertion.tool_name
            ]
            verdict = not matched
            refs = [event.id for event in matched]
        elif assertion.kind == "tool_call_order":
            actual = [str(event.payload.get("tool_name")) for event in tool_calls]
            verdict = self._is_subsequence(assertion.tool_names or [], actual)
            refs = [event.id for event in tool_calls]
        elif assertion.kind == "tool_arguments_equal":
            matched = [
                event
                for event in tool_calls
                if event.payload.get("tool_name") == assertion.tool_name
                and assertion.expected_arguments == event.payload.get("arguments")
            ]
            verdict = bool(matched)
            refs = [event.id for event in matched]
        elif assertion.kind == "tool_arguments_schema":
            candidates = [
                event for event in tool_calls if event.payload.get("tool_name") == assertion.tool_name
            ]
            matched = [
                event
                for event in candidates
                if Draft202012Validator(assertion.arguments_schema or {}).is_valid(
                    event.payload.get("arguments")
                )
            ]
            verdict = bool(matched)
            refs = [event.id for event in candidates]
        elif assertion.kind == "text_contains":
            matched = [
                event
                for event in messages
                if (assertion.value or "") in str(event.payload.get("text", ""))
            ]
            verdict = bool(matched)
            refs = [event.id for event in matched]
        elif assertion.kind == "text_regex":
            pattern = re.compile(assertion.value or "")
            matched = [
                event
                for event in messages
                if pattern.search(str(event.payload.get("text", ""))) is not None
            ]
            verdict = bool(matched)
            refs = [event.id for event in matched]
        elif assertion.kind == "no_execution_error":
            verdict = not errors
            refs = [event.id for event in errors]

        return EvaluationCriterion(
            criterion=description,
            verdict="pass" if verdict else "fail",
            evidence_refs=refs,
        )

    @staticmethod
    def _description(assertion: Assertion) -> str:
        suffix = f" in turn {assertion.turn_position}" if assertion.turn_position else ""
        if assertion.kind == "first_action":
            return f"first action is {assertion.expected_action}{suffix}"
        if assertion.tool_name:
            return f"{assertion.kind}: {assertion.tool_name}{suffix}"
        if assertion.tool_names:
            return f"{assertion.kind}: {' -> '.join(assertion.tool_names)}{suffix}"
        if assertion.value:
            return f"{assertion.kind}: {assertion.value}{suffix}"
        return f"{assertion.kind}{suffix}"

    @staticmethod
    def _is_subsequence(expected: list[str], actual: list[str]) -> bool:
        iterator = iter(actual)
        return all(any(candidate == item for candidate in iterator) for item in expected)
