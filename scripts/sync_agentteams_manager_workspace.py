"""Install the AgentRig Manager overlay into the local HiClaw workspace."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

BLOCK_START = "<!-- agentrig-local-overlay-start -->"
BLOCK_END = "<!-- agentrig-local-overlay-end -->"


def upsert_overlay(target: Path, overlay: Path) -> None:
    existing = target.read_text() if target.exists() else ""
    pattern = re.compile(
        rf"\n*{re.escape(BLOCK_START)}.*?{re.escape(BLOCK_END)}\n*",
        re.DOTALL,
    )
    base = pattern.sub("\n", existing).rstrip()
    custom = overlay.read_text().strip()
    target.write_text(
        f"{base}\n\n{BLOCK_START}\n{custom}\n{BLOCK_END}\n",
    )


def sync_workspace(root: Path, workspace: Path) -> None:
    package = root / "deploy" / "agentteams" / "packages" / "manager"
    workspace.mkdir(parents=True, exist_ok=True)
    for filename in ("SOUL.md", "AGENTS.md"):
        upsert_overlay(workspace / filename, package / filename)

    skill_root = root / "skills" / "manager"
    destination = workspace / "skills"
    destination.mkdir(parents=True, exist_ok=True)
    for skill_name in (
        "plan-evaluation",
        "execute-evaluation-plan",
        "diagnose-run",
        "build-test-case-draft",
        "configure-test-target",
    ):
        shutil.copytree(
            skill_root / skill_name,
            destination / skill_name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("agents"),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sync_workspace(root, args.workspace.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
