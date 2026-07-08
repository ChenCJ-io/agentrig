"""mock 策略实现：L0 内联 / L1 剧本回放 / L2 样本库。

ToolMockHub 路由 L0 > L1 > L2，实现 MockPolicy 接口，接入 proxy 的 mock_policy
（替换 StaticMockPolicy 占位）。L3 模拟器在 MCP proxy 模式下弃用（真实后端提供工具）。
"""

from .hub import ToolMockHub
from .samples import Sample, SampleStore
from .script import MockScript

__all__ = ["MockScript", "Sample", "SampleStore", "ToolMockHub"]
