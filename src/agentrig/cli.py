"""AgentRig CLI 入口（`agentrig serve`）。"""
from __future__ import annotations

import argparse

import uvicorn

from .config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentrig", description="AgentRig 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="启动 AgentRig 服务")
    serve.add_argument("--reload", action="store_true", help="启用热重载")
    serve.add_argument("--host", default=None, help="覆盖监听 host")
    serve.add_argument("--port", type=int, default=None, help="覆盖监听端口")

    args = parser.parse_args()

    if args.cmd == "serve":
        settings = get_settings()
        host: str = args.host if args.host is not None else settings.server.host
        port: int = args.port if args.port is not None else settings.server.port
        uvicorn.run("agentrig.app:app", host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
