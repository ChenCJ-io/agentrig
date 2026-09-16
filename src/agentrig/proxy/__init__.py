"""AgentRig V1 MCP Proxy。"""

from .aggregator import AgentRigProxy
from .backend import NAMESPACE_SEP, BackendRegistry

__all__ = [
    "AgentRigProxy",
    "BackendRegistry",
    "NAMESPACE_SEP",
]
