"""Alembic 资源定位与当前 schema revision。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


@contextmanager
def migration_config() -> Iterator[Config]:
    """定位源码树或 wheel 内随包发布的 Alembic 资源。"""

    repository_root = Path(__file__).resolve().parents[4]
    source_config = repository_root / "alembic.ini"
    source_migrations = repository_root / "migrations"
    if source_config.is_file() and source_migrations.is_dir():
        config = Config(str(source_config))
        config.set_main_option("script_location", str(source_migrations))
        yield config
        return

    package = files("agentrig")
    with (
        as_file(package.joinpath("alembic.ini")) as config_path,
        as_file(package.joinpath("migrations")) as migrations_path,
    ):
        config = Config(str(config_path))
        config.set_main_option("script_location", str(migrations_path))
        yield config


def migration_heads() -> tuple[str, ...]:
    """返回随当前代码发布的 Alembic head revision。"""

    with migration_config() as config:
        return tuple(ScriptDirectory.from_config(config).get_heads())
