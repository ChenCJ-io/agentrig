from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from scripts.build_agentteams_packages import ROLES, build


def test_agentteams_packages_use_v112_import_layout(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]

    built = build(root, tmp_path)

    assert {item.name for item in built} == {
        "agentrig-manager.zip",
        "agentrig-curator.zip",
        "agentrig-judge.zip",
    }
    for role, skill_names in ROLES.items():
        with ZipFile(tmp_path / f"agentrig-{role}.zip") as archive:
            names = set(archive.namelist())
        assert "config/SOUL.md" in names
        assert "config/AGENTS.md" in names
        assert "SOUL.md" not in names
        assert "AGENTS.md" not in names
        for skill_name in skill_names:
            assert f"skills/{skill_name}/SKILL.md" in names
