"""Validate every repository Skill and its role/package contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentrig.skill_contracts import validate_skill_contracts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    manifest = validate_skill_contracts(args.repository_root)
    print(
        json.dumps(
            {
                "schema_version": manifest.schema_version,
                "skill_count": len(manifest.skills),
                "manifest_hash": manifest.content_hash,
                "status": "pass",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
