"""LassistTransport：Lassist 式 SSE 中间人 transport（真实 transport 参考实现）。

连一个 Lassist 式 agent（POST `/chat/stream`，SSE 响应）。transport 持有 session_id
（首话由 agent 在 `session_created` 事件返回，后续请求带）。mock 生成在 CaseRunner
（不在 transport）—— 这是 AgentTransport 抽象的核心，与老代码 `agent_client` 把
mock 焊死在 transport 内相反。

参考老代码 `agent_client.AgentSSEClient` 的 SSE 解析 + 请求格式，去掉 Pixcake 专有
字段（device_info / chat_channel / user_id），留通用 Lassist 协议核心。

开源用户参考它写自己的 transport（OpenAI / Anthropic / 自研协议）。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..models import ToolResult
from .base import AgentTransport, EventType, NormalizedEvent


class LassistTransport(AgentTransport):
    """连 Lassist 式 agent（POST /chat/stream + SSE 响应）。

    session_id 由 agent 在 session_created 事件返回，transport 持有；
    后续 send_tool_results 用它回灌（Lassist 协议：回灌必须有 session_id）。
    """

    def __init__(self, base_url: str, *, request_timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.session_id: str | None = None

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
        del session_id  # Lassist 协议用 transport 持有的 session_id
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
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
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
    """构造 tool_result 请求体的一项（对齐老代码 build_agent_result_item）。

    result 序列化为 JSON 字符串（Lassist 协议要求字符串，不是对象）。
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
    """解析 SSE data: 行（Lassist 格式：data: {type, run_id, data}）。"""
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
    """把 Lassist SSE 事件归一成 NormalizedEvent。外层 {type, run_id, data}。"""
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
