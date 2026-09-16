"""Render a content-free GitHub Check summary from the canonical Gate JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath

from agentrig.gates import ReleaseGateResult
from agentrig.reporting import ComparisonReport, QualityReport


def resolve_evidence(pointer_path: Path) -> tuple[Path, Path, Path]:
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    value = pointer.get("path")
    if not isinstance(value, str):
        raise ValueError("evidence pointer is missing path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != value
        or value in {"", "."}
    ):
        raise ValueError("evidence pointer path must be normalized and relative")
    directory = (pointer_path.parent / Path(*relative.parts)).resolve()
    root = pointer_path.parent.resolve()
    if not directory.is_relative_to(root):
        raise ValueError("evidence pointer escapes its state directory")
    return (
        directory / "quality-report.json",
        directory / "comparison-report.json",
        directory / "release-gate.json",
    )


def render_summary(
    quality: QualityReport,
    comparison: ComparisonReport,
    gate: ReleaseGateResult,
) -> str:
    hashes = {
        quality.source_snapshot_hash,
        comparison.source_snapshot_hash,
        gate.source_snapshot_hash,
    }
    if len(hashes) != 1 or len({quality.run_id, comparison.run_id, gate.run_id}) != 1:
        raise ValueError("Quality, Comparison, and Gate inputs are not from one Run snapshot")
    icon = {"pass": "✅", "warn": "⚠️", "fail": "❌", "inconclusive": "❔"}[
        gate.verdict
    ]
    check_rows = [
        (
            f"| `{item.name}` | {item.severity} | **{item.outcome}** | "
            f"`{item.actual}` {item.operator} `{item.threshold}` |"
        )
        for item in gate.checks
    ]
    return "\n".join(
        [
            f"## {icon} AgentRig Release Gate: `{gate.verdict}`",
            "",
            "> This summary is rendered from the same server-generated Gate JSON used by CLI and Web. It contains no prompt or tool-result bodies.",
            "",
            f"- Run: `{gate.run_id}`",
            f"- Policy: `{gate.policy_name}@{gate.policy_version}` (`{gate.policy_hash}`)",
            f"- Source snapshot: `{gate.source_snapshot_hash}`",
            f"- Result hash: `{gate.result_hash}`",
            f"- Regressions: **{comparison.summary.regression_count}**",
            f"- Incomparable environments: **{comparison.summary.incomparable_environment_count}**",
            f"- Evidence reference validity: `{quality.evidence_quality.reference_validity_rate}`",
            "",
            "| Check | Severity | Outcome | Actual / threshold |",
            "| --- | --- | --- | --- |",
            *check_rows,
            "",
            "The complete Quality, Comparison, and Gate JSON files are uploaded as workflow artifacts.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-pointer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    quality_path, comparison_path, gate_path = resolve_evidence(args.evidence_pointer)
    quality = QualityReport.model_validate_json(quality_path.read_text(encoding="utf-8"))
    comparison = ComparisonReport.model_validate_json(
        comparison_path.read_text(encoding="utf-8")
    )
    gate = ReleaseGateResult.model_validate_json(gate_path.read_text(encoding="utf-8"))
    mode = "a" if args.append else "w"
    with args.output.open(mode, encoding="utf-8") as destination:
        destination.write(render_summary(quality, comparison, gate))
    print(
        json.dumps(
            {"run_id": gate.run_id, "verdict": gate.verdict, "result_hash": gate.result_hash},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
