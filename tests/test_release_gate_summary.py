from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.render_release_gate_summary import render_summary, resolve_evidence

from agentrig.evaluations.models import EvaluationOutcome
from agentrig.gates import ReleasePolicy, evaluate_release_gate
from agentrig.reporting.quality import build_comparison_report, build_quality_report
from tests.test_quality_gate import _detail, _run


def test_github_summary_uses_the_canonical_gate_and_excludes_content() -> None:
    details = [
        _detail("baseline", EvaluationOutcome.PASS, duration_seconds=1, input_tokens=10, output_tokens=2),
        _detail("candidate", EvaluationOutcome.FAIL, duration_seconds=1, input_tokens=10, output_tokens=2),
    ]
    quality = build_quality_report(_run(), details)
    comparison = build_comparison_report(_run(), details)
    gate = evaluate_release_gate(
        quality,
        comparison,
        ReleasePolicy(name="test-policy"),
    )

    summary = render_summary(quality, comparison, gate)

    assert "AgentRig Release Gate: `fail`" in summary
    assert gate.result_hash in summary
    assert quality.source_snapshot_hash in summary
    assert "must-not-be-exported" not in summary.casefold()
    assert "tool-result" in summary.casefold()  # only the explicit exclusion notice


def test_evidence_pointer_rejects_parent_traversal(tmp_path: Path) -> None:
    pointer = tmp_path / "latest-evidence.json"
    pointer.write_text(json.dumps({"path": "../outside"}), encoding="utf-8")

    with pytest.raises(ValueError, match="normalized and relative"):
        resolve_evidence(pointer)
