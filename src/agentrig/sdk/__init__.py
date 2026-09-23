"""AgentRig Python SDK：不改 Agent 结构，让现有 Python Agent 接受 AgentRig 驱动。

Agno 与 LangGraph 的工具由 harness 在加载时自动接管，无需改代码；不依赖框架的函数工具
用 :func:`tool` 标记。本包运行在被测 Agent 自己的解释器里，只依赖标准库，框架适配器
按需惰性导入，并保持 Python 3.10 兼容。
"""

from __future__ import annotations

from ._runtime import HarnessContext, current
from ._tools import tool

__all__ = ["HarnessContext", "current", "tool"]
