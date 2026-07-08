"""EchoTransport：脚本驱动的 transport，绕过 HTTP。

用于在不接真实 agent 的情况下验证 AgentTransport 抽象 + CaseRunner 胶水层。
mock 生成在 CaseRunner —— EchoTransport 只回放 agent 对用户消息或
tool_result 回灌的反应。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..models import ToolResult
from .base import NormalizedEvent


@dataclass
class EchoScript:
    """预设的 agent 响应剧本。

    `on_user_message[0]` 在首次 `send_user_message` 时回放。
    `on_tool_results[i]` 在一轮内第 i 次 `send_tool_results` 时回放
    （按工具调用顺序索引）。
    """

    on_user_message: list[list[NormalizedEvent]] = field(default_factory=list)
    on_tool_results: dict[int, list[NormalizedEvent]] = field(default_factory=dict)


class EchoTransport:
    """脚本化 transport，实现 `AgentTransport`。"""

    def __init__(self, script: EchoScript) -> None:
        self.script = script
        self._turn_index = 0

    async def send_user_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        del message, session_id, attachments, metadata  # 脚本驱动，不用
        self._turn_index = 0
        for ev in self.script.on_user_message[0]:
            yield ev

    async def send_tool_results(
        self,
        results: list[ToolResult],
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        del session_id
        for _r in results:
            idx = self._turn_index
            self._turn_index += 1
            for ev in self.script.on_tool_results.get(idx, []):
                yield ev
