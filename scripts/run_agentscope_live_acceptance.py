"""Run an explicit AgentScope 2.x AG-UI live probe and write a versioned report."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agentrig.infrastructure.secrets import SecretResolver
from agentrig.targets.agentscope_compat import collect_agentscope_live_compat


async def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-version", default="2.0.6")
    parser.add_argument("--run-path", default="/agui")
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--capability-path", default="/capabilities")
    parser.add_argument("--secret-ref")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    args = parser.parse_args()
    secret = SecretResolver().resolve(args.secret_ref)
    report = await collect_agentscope_live_compat(
        args.endpoint,
        expected_version=args.expected_version or None,
        run_path=args.run_path,
        health_path=args.health_path,
        capability_path=args.capability_path,
        secret_value=secret,
        timeout_seconds=args.timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "verdict": report.verdict,
                "result_hash": report.result_hash,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return {"pass": 0, "fail": 2, "inconclusive": 3}[report.verdict]


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
