"""transports：被测 agent 的协议适配层。

每个 transport 实现 `AgentTransport`，驱动一种 agent 协议（streaming-chat SSE /
OpenAI streaming / MCP / 内存 echo），产出 `NormalizedEvent` 流。
mock 生成在 CaseRunner，不在这里。
"""

from .base import AgentTransport, EventType, NormalizedEvent

__all__ = ["AgentTransport", "EventType", "NormalizedEvent"]
