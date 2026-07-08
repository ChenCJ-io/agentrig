"""AgentRig MCP Proxy/Aggregator。

对 agent 是 MCP server（聚合后端工具，命名空间前缀化暴露），对后端真实
MCP server 是 MCP client。mock 注入 + trace 记录在转发链路里
（详见 aggregator.py）。
"""

from .aggregator import AgentRigProxy
from .backend import NAMESPACE_SEP, BackendRegistry
from .mock_policy import MockPolicy, StaticMockPolicy
from .trace import TraceEntry, TraceSink

__all__ = [
    "AgentRigProxy",
    "BackendRegistry",
    "MockPolicy",
    "NAMESPACE_SEP",
    "StaticMockPolicy",
    "TraceEntry",
    "TraceSink",
]
