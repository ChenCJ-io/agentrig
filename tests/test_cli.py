"""CLI 安装与默认运行目录回归。"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import agentrig


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
