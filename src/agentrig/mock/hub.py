"""ToolMockHub：L0 内联 > L1 剧本 > L2 样本库。

实现 MockPolicy 接口，接入 proxy 的 mock_policy（替换 StaticMockPolicy）。
L0 内联是 per-turn 的（CaseRunner 在每轮设置/清理，最高优先级）。
"""
from __future__ import annotations

from typing import Any

from ..proxy.mock_policy import MockPolicy
from .samples import SampleStore
from .script import MockScript


class ToolMockHub(MockPolicy):
    """三层 mock 路由：L0 内联 > L1 剧本 > L2 样本库。"""

    def __init__(
        self,
        *,
        script: MockScript | None = None,
        samples: SampleStore | None = None,
    ) -> None:
        self.script = script or MockScript()
        self.samples = samples or SampleStore()
        self._inline: dict[str, Any] = {}

    # —— L0 内联（per-turn，CaseRunner 设置/清理）——
    def set_inline(self, tool_name: str, result: Any) -> None:
        """设置当前 turn 的内联 mock（最高优先级）。"""
        self._inline[tool_name] = result

    def clear_inline(self) -> None:
        """清理所有内联 mock（每轮结束调）。"""
        self._inline.clear()

    # —— MockPolicy 接口 ——
    def should_mock(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if tool_name in self._inline:  # L0
            return True
        if self.script.has(tool_name):  # L1
            return True
        if self.samples.find(tool_name, arguments) is not None:  # L2
            return True
        return False

    def generate(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if tool_name in self._inline:  # L0
            return self._inline[tool_name]
        if self.script.has(tool_name):  # L1
            r = self.script.next(tool_name)
            if r is not None:
                return r
        r = self.samples.find(tool_name, arguments)  # L2
        if r is not None:
            return r
        # should_mock 已确认有 mock，到这里说明状态不一致
        raise RuntimeError(f"should_mock 为 true 但找不到 mock: {tool_name}")
