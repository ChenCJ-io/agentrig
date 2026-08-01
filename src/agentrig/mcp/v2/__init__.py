"""V2 角色隔离 MCP 工具注册表。"""

from .manager import register as register_manager_tools
from .workers import register_curator, register_judge

__all__ = ["register_curator", "register_judge", "register_manager_tools"]
