"""按业务能力注册 V1 原子 MCP Tools。"""

from mcp.server.fastmcp import FastMCP

from ...bootstrap import ServiceContainer
from . import cases, execution, profiles, samples, targets


def register_all(server: FastMCP, services: ServiceContainer) -> None:
    cases.register(server, services)
    execution.register(server, services)
    targets.register(server, services)
    profiles.register(server, services)
    samples.register(server, services)
