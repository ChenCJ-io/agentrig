"""StreamingChatTransport：streaming-chat 式 SSE agent 的参考 transport。

连一个外置 tool-calling 的 streaming-chat agent（POST `/chat/stream`，SSE 响应）。
transport 持有 session_id（首话由 agent 在 `session_created` 事件返回，后续请求带）。
mock 生成在 CaseRunner（不在 transport）—— 这是 AgentTransport 抽象的核心：
transport 只驱动一段对话并把响应归一成 `NormalizedEvent`，工具返回由调用方注入。

协议是「外置 tool-calling 往返」的一种实现（agent 把 tool_call 暴露在对话流里，
而非内部闭环），天然让 AgentRig 做中间人。开源用户参考它写自己的 transport
（OpenAI streaming / Anthropic / 自研协议）。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..models import ToolResult
from .base import AgentTransport, EventType, NormalizedEvent


class StreamingChatTransport(AgentTransport):
    """连 streaming-chat 式 agent（POST /chat/stream + SSE 响应）。

    session_id 由 agent 在 session_created 事件返回，transport 持有；
    后续 send_tool_results 用它回灌（协议：回灌必须带 session_id）。

    transport 参数可选，注入 httpx transport（如 ASGITransport）做内进程测试；
    默认 None 走真实 HTTP。
    """

    def __init__(
        self,
        base_url: str,
        *,
        request_timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.session_id: str | None = None
        self._transport = transport

    async def send_user_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        if session_id is not None:
            self.session_id = session_id
        payload: dict[str, Any] = {"type": "chat", "message": message}
        if self.session_id is not None:
            payload["session_id"] = self.session_id
        if attachments:
            payload["attachments"] = attachments
        if metadata:
            payload["metadata"] = metadata

        async for ev in self._post_and_stream(payload):
            yield ev

    async def send_tool_results(
        self,
        results: list[ToolResult],
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[NormalizedEvent]:
        del session_id  # 协议用 transport 持有的 session_id
        if self.session_id is None:
            yield NormalizedEvent(type=EventType.ERROR, error="no session_id for tool_result")
            return
        payload = {
            "type": "tool_result",
            "session_id": self.session_id,
            "tool_results": [_build_tool_result_item(r) for r in results],
        }
        async for ev in self._post_and_stream(payload):
            yield ev

    async def _post_and_stream(self, payload: dict[str, Any]) -> AsyncIterator[NormalizedEvent]:
        """POST /chat/stream，读 SSE，归一事件。"""
        url = f"{self.base_url}/chat/stream"
        headers = {"Accept": "text/event-stream"}
        client_kwargs: dict[str, Any] = {"timeout": self.request_timeout}
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    ev = _parse_sse_line(line)
                    if ev is None:
                        continue
                    if ev.type is EventType.SESSION_CREATED and ev.session_id:
                        self.session_id = ev.session_id
                    yield ev


def _build_tool_result_item(r: ToolResult) -> dict[str, Any]:
    """构造 tool_result 请求体的一项。

    result 序列化为 JSON 字符串（协议要求字符串，不是对象）。
    """
    result_str = r.result if isinstance(r.result, str) else json.dumps(
        r.result, ensure_ascii=False
    )
    return {
        "tool_call_id": r.tool_call_id,
        "name": r.name,
        "result": result_str,
        "status": "success",
    }


def _parse_sse_line(line: str) -> NormalizedEvent | None:
    """解析 SSE data: 行（streaming-chat 格式：data: {type, run_id, data}）。"""
    if not line.startswith("data:"):
        return None
    data_str = line[5:].strip()
    if not data_str:
        return None
    try:
        raw = json.loads(data_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    return _normalize(raw)


def _normalize(raw: dict[str, Any]) -> NormalizedEvent | None:
    """把 streaming-chat SSE 事件归一成 NormalizedEvent。外层 {type, run_id, data}。"""
    ev_type = raw.get("type")
    data = raw.get("data") or {}

    if ev_type == "session_created":
        return NormalizedEvent(type=EventType.SESSION_CREATED, session_id=data.get("session_id"))
    if ev_type == "text_delta":
        return NormalizedEvent(type=EventType.TEXT_DELTA, text=data.get("text", ""))
    if ev_type == "tool_calls":
        calls = [
            {
                "tool_call_id": tc.get("id", ""),
                "name": tc.get("name", ""),
                "arguments": tc.get("input", {}),
            }
            for tc in data.get("tool_calls", [])
        ]
        return NormalizedEvent(type=EventType.TOOL_CALLS, tool_calls=calls)
    if ev_type == "todos":
        return NormalizedEvent(type=EventType.TODOS, todos=data.get("items", []))
    if ev_type == "done":
        return NormalizedEvent(type=EventType.DONE)
    if ev_type == "error":
        return NormalizedEvent(type=EventType.ERROR, error=str(data.get("message", "unknown error")))
    return None  # suggestions/questions/session_title/... 第一周不归一
