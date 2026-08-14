"""CLI 安装与默认运行目录回归。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from argparse import Namespace
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

import agentrig
from agentrig.cli import (
    _build_parser,
    _gate_exit_code,
    _run_agentteams_compat_command,
    _safety_exit_code,
)
from agentrig.gates import ReleaseGateResult
from agentrig.infrastructure.database import Database, DatabaseSchemaError
from agentrig.infrastructure.database.migrations import migration_heads


def test_package_and_runtime_versions_match() -> None:
    assert agentrig.__version__ == version("agentrig")


def test_report_and_gate_cli_contracts_and_exit_codes() -> None:
    parser = _build_parser()
    report = parser.parse_args(
        ["report", "quality", "--run-id", "run_1", "--format", "markdown"]
    )
    gate = parser.parse_args(
        ["gate", "evaluate", "--run-id", "run_1", "--policy", "policy.json"]
    )
    safety = parser.parse_args(["safety", "gate", "--run-id", "run_1"])
    compat = parser.parse_args(
        [
            "agentteams-compat",
            "--manifest",
            "manifest.json",
            "--observation",
            "observation.json",
        ]
    )
    assert report.report_kind == "quality"
    assert report.format == "markdown"
    assert gate.gate_action == "evaluate"
    assert safety.safety_action == "gate"
    assert safety.suite_version == "1.0.0"
    assert compat.output == "-"

    base: dict[str, Any] = {
        "generated_at": "2026-08-10T00:00:00Z",
        "run_id": "run_1",
        "policy_name": "test",
        "policy_version": "1",
        "policy_hash": "sha256:policy",
        "source_snapshot_hash": "sha256:source",
        "result_hash": "sha256:result",
        "checks": [],
    }
    assert _gate_exit_code(
        ReleaseGateResult(verdict="pass", **base),
        fail_on_warn=False,
    ) == 0
    assert _gate_exit_code(
        ReleaseGateResult(verdict="warn", **base),
        fail_on_warn=True,
    ) == 2
    assert _gate_exit_code(
        ReleaseGateResult(verdict="fail", **base),
        fail_on_warn=False,
    ) == 2
    assert _gate_exit_code(
        ReleaseGateResult(verdict="inconclusive", **base),
        fail_on_warn=False,
    ) == 3
    assert _safety_exit_code("passed") == 0
    assert _safety_exit_code("blocked") == 2
    assert _safety_exit_code("inconclusive") == 3


def test_agentteams_compat_cli_writes_versioned_report(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest = (
        repository_root
        / "deploy"
        / "agentteams"
        / "profiles"
        / "v1.2.2-current"
        / "manifest.json"
    )
    observation = tmp_path / "observation.json"
    output = tmp_path / "compat-report.json"
    observation.write_text(
        json.dumps(
            {
                "schema_version": "agentrig.agentteams-observation.v1",
                "observed_at": "2026-08-10T00:00:00Z",
                "runtime": {
                    "version": "v1.2.2",
                    "runtime_version": "1.2.2",
                    "resource_api_version": "agentteams.io/v1beta1",
                    "transport_health": "healthy",
                },
                "skills": [],
                "memberships": [],
                "invocations": [],
                "evidence_refs": ["registry:local-contract"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = _run_agentteams_compat_command(
        Namespace(
            manifest=str(manifest),
            observation=str(observation),
            output=str(output),
        )
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 3
    assert report["schema_version"] == "agentrig.agentteams-compat-report.v1"
    assert report["profile"] == "v1.2.2-current"
    assert report["observed_at"] == "2026-08-10T00:00:00Z"
    assert report["result_hash"].startswith("sha256:")
    assert report["failures"] == []
    assert report["limitations"] == [
        "invocation_route_not_observed",
        "skill_distribution_not_observed",
    ]


def test_db_upgrade_creates_default_sqlite_parent(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("AGENTRIG_DATABASE__URL", None)
    executable = Path(sys.executable).with_name("agentrig")

    completed = subprocess.run(
        [str(executable), "db", "upgrade"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / ".agentrig" / "agentrig.db").is_file()


async def test_persistent_database_requires_alembic_upgrade(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'unversioned.db'}")
    await database.create_schema()
    try:
        with pytest.raises(DatabaseSchemaError, match="not initialized by Alembic"):
            await database.initialize_schema()
    finally:
        await database.dispose()


async def test_db_upgrade_records_current_head(tmp_path: Path) -> None:
    database_path = tmp_path / "migrated.db"
    environment = os.environ.copy()
    environment["AGENTRIG_DATABASE__URL"] = f"sqlite+aiosqlite:///{database_path}"
    executable = Path(sys.executable).with_name("agentrig")

    completed = subprocess.run(
        [str(executable), "db", "upgrade"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert migration_heads() == ("20260811_0007",)
    with sqlite3.connect(database_path) as connection:
        assistant_event_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(assistant_events)").fetchall()
        }
        evaluation_plan_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(evaluation_plans)").fetchall()
        }
    assert "decision_id" in assistant_event_columns
    assert "origin_decision_id" in evaluation_plan_columns
    database = Database(f"sqlite+aiosqlite:///{database_path}")
    try:
        await database.initialize_schema()
    finally:
        await database.dispose()
