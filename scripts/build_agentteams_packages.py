"""Build deterministic, version-explicit AgentTeams Manager/Worker packages."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from agentrig.skill_contracts import validate_skill_contracts

ROLES = {
    "manager": [
        "adaptive-evaluation",
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
    add_bytes(archive, source.read_bytes(), destination)


def add_bytes(archive: ZipFile, content: bytes, destination: str) -> None:
    info = ZipInfo(destination, date_time=(2026, 8, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def build(
    root: Path,
    output: Path,
    *,
    profile: str = "v1.1.2-competition",
) -> list[Path]:
    contract_manifest = validate_skill_contracts(root)
    contracts = {item.id: item for item in contract_manifest.skills}
    runtime = "openclaw" if profile == "v1.1.2-competition" else "qwenpaw"
    agentteams_version = "v1.1.2" if profile == "v1.1.2-competition" else "v1.2.2"
    output.mkdir(parents=True, exist_ok=True)
    built: list[Path] = []
    for role, skill_names in ROLES.items():
        destination = output / f"agentrig-{role}.zip"
        package = root / "deploy" / "agentteams" / "packages" / role
        with ZipFile(destination, "w") as archive:
            manifest: dict[str, object] = {
                "version": "1.0",
                "source": {"hostname": "agentrig-build"},
                "worker": {
                    "suggested_name": f"agentrig-{role}",
                    "runtime": runtime,
                    "apt_packages": [],
                    "pip_packages": [],
                    "npm_packages": [],
                },
            }
            if profile == "v1.2.2-current":
                manifest["agentrig_contract"] = {
                    "schema_version": "agentrig.agentteams-package.v1",
                    "profile": profile,
                    "agentteams_version": agentteams_version,
                    "role": role,
                    "skill_contract_manifest_hash": contract_manifest.content_hash,
                    "skills": [
                        {
                            "id": skill_name,
                            "contract_version": contracts[skill_name].contract_version,
                            "content_sha256": contracts[skill_name].content_sha256,
                        }
                        for skill_name in skill_names
                    ],
                }
            add_bytes(
                archive,
                (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode(),
                "manifest.json",
            )
            for name in ("SOUL.md", "AGENTS.md"):
                # AgentTeams v1.1.2 imports role configuration from config/.
                # Root-level SOUL.md is only a compatibility fallback and root-level
                # AGENTS.md is not imported by the controller package resolver.
                add_file(archive, package / name, str(Path("config") / name))
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
    parser.add_argument(
        "--profile",
        choices=("v1.1.2-competition", "v1.2.2-current"),
        default="v1.1.2-competition",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output if args.output.is_absolute() else root / args.output
    if output.exists():
        shutil.rmtree(output)
    for item in build(root, output, profile=args.profile):
        print(item.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
