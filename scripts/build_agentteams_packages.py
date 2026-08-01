"""Build deterministic AgentTeams v1.1.2 Manager/Worker package archives."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROLES = {
    "manager": [
        "plan-evaluation",
        "execute-evaluation-plan",
        "diagnose-run",
        "build-test-case-draft",
        "configure-test-target",
    ],
    "curator": ["simulate-tool-result"],
    "judge": ["judge-evidence"],
}


def add_file(archive: ZipFile, source: Path, destination: str) -> None:
    info = ZipInfo(destination, date_time=(2026, 8, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, source.read_bytes())


def build(root: Path, output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    for role, skill_names in ROLES.items():
        destination = output / f"agentrig-{role}.zip"
        package = root / "deploy" / "agentteams" / "packages" / role
        with ZipFile(destination, "w") as archive:
            for name in ("SOUL.md", "AGENTS.md"):
                add_file(archive, package / name, name)
            skill_root = root / "skills" / ("manager" if role == "manager" else "workers")
            for skill_name in skill_names:
                skill = skill_root / skill_name
                for source in sorted(path for path in skill.rglob("*") if path.is_file()):
                    relative = source.relative_to(skill)
                    if relative.parts[:1] == ("agents",):
                        continue
                    add_file(
                        archive,
                        source,
                        str(Path("skills") / skill_name / relative),
                    )
        built.append(destination)
    return built


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("deploy/agentteams/dist"),
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        shutil.rmtree(output)
    for item in build(root, output):
        print(item.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
