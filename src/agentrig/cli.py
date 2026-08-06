"""AgentRig CLI 入口。"""
from __future__ import annotations

import argparse
import asyncio

import uvicorn

from .config import get_settings
from .infrastructure.database.migrations import migration_config


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
        with migration_config() as config:
            if args.action == "upgrade":
                command.upgrade(config, "head")
            elif args.action == "downgrade":
                command.downgrade(config, "-1")
            else:
                command.current(config, verbose=True)
if __name__ == "__main__":
    main()
