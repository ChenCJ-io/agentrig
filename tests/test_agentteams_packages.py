from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from scripts.build_agentteams_packages import ROLES, build
from scripts.sync_agentteams_manager_workspace import BLOCK_START, sync_workspace


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
            manifest = json.loads(archive.read("manifest.json"))
        assert manifest["version"] == "1.0"
        assert manifest["worker"]["runtime"] == "openclaw"
        assert manifest["worker"]["suggested_name"] == f"agentrig-{role}"
        assert "config/SOUL.md" in names
        assert "config/AGENTS.md" in names
        assert "SOUL.md" not in names
        assert "AGENTS.md" not in names
        for skill_name in skill_names:
            assert f"skills/{skill_name}/SKILL.md" in names


def test_manager_workspace_overlay_is_idempotent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "AGENTS.md").write_text("builtin agents\n")
    (tmp_path / "SOUL.md").write_text("builtin soul\n")

    sync_workspace(root, tmp_path)
    sync_workspace(root, tmp_path)

    agents = (tmp_path / "AGENTS.md").read_text()
    soul = (tmp_path / "SOUL.md").read_text()
    assert agents.startswith("builtin agents")
    assert soul.startswith("builtin soul")
    assert agents.count(BLOCK_START) == 1
    assert soul.count(BLOCK_START) == 1
    assert "AgentRig request envelope" in agents
    assert (tmp_path / "skills" / "plan-evaluation" / "SKILL.md").is_file()
    assert not (
        tmp_path / "skills" / "plan-evaluation" / "agents" / "openai.yaml"
    ).exists()
