"""被测 Target 与版本配置领域模块。"""

from .schemas import TargetCreate, TargetPatch, TargetVersion, TargetView
from .service import TargetService

__all__ = ["TargetCreate", "TargetPatch", "TargetService", "TargetVersion", "TargetView"]
