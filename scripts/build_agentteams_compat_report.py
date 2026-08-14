"""Build a deterministic AgentTeams compatibility report from observed JSON evidence."""

from __future__ import annotations

import argparse
from pathlib import Path

from agentrig.integrations.agentteams.compat import (
    AgentTeamsObservation,
    AgentTeamsProfileManifest,
    adapter_for,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = AgentTeamsProfileManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    observed = AgentTeamsObservation.model_validate_json(
        args.observation.read_text(encoding="utf-8")
    )
    report = adapter_for(manifest).capability_report(
        runtime_observation=observed.runtime,
        skills=observed.skills,
        memberships=observed.memberships,
        invocations=observed.invocations,
        evidence_refs=observed.evidence_refs,
        observed_at=observed.observed_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(args.output)
    if report.failures:
        return 2
    return 3 if report.limitations else 0


if __name__ == "__main__":
    raise SystemExit(main())
