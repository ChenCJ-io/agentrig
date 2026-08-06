"""CLI 安装与默认运行目录回归。"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

import agentrig
from agentrig.infrastructure.database import Database, DatabaseSchemaError
from agentrig.infrastructure.database.migrations import migration_heads


def test_package_and_runtime_versions_match() -> None:
    assert agentrig.__version__ == version("agentrig")


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
    assert migration_heads() == ("20260804_0004",)
    database = Database(f"sqlite+aiosqlite:///{database_path}")
    try:
        await database.initialize_schema()
    finally:
        await database.dispose()
