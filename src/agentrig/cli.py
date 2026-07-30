"""AgentRig CLI 入口。"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

import uvicorn
from alembic.config import Config

from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentrig", description="AgentRig 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="启动 AgentRig 服务")
    serve.add_argument("--reload", action="store_true", help="启用热重载")
    serve.add_argument("--host", default=None, help="覆盖监听 host")
    serve.add_argument("--port", type=int, default=None, help="覆盖监听端口")

    sub.add_parser("demo", help="一键验收 V1 异步执行、Fixture 和 Rule 闭环")
    database = sub.add_parser("db", help="管理 AgentRig 数据库迁移")
    database.add_argument(
        "action",
        choices=["upgrade", "downgrade", "current"],
        help="upgrade 到最新、downgrade 一个版本或查看当前版本",
    )

    args = parser.parse_args()

    if args.cmd == "serve":
        settings = get_settings()
        host: str = args.host if args.host is not None else settings.server.host
        port: int = args.port if args.port is not None else settings.server.port
        uvicorn.run("agentrig.app:app", host=host, port=port, reload=args.reload)
    elif args.cmd == "demo":
        from .demo import run_demo

        raise SystemExit(asyncio.run(run_demo()))
    elif args.cmd == "db":
        from alembic import command
        with _migration_config() as config:
            if args.action == "upgrade":
                command.upgrade(config, "head")
            elif args.action == "downgrade":
                command.downgrade(config, "-1")
            else:
                command.current(config, verbose=True)


@contextmanager
def _migration_config() -> Iterator[Config]:
    """定位源码树或 wheel 内随包发布的 Alembic 资源。"""

    repository_root = Path(__file__).resolve().parents[2]
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


if __name__ == "__main__":
    main()
