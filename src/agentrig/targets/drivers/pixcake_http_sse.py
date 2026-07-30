"""当前 Pixcake Agent ``/chat/stream`` 协议适配。

事件仍复用通用 HTTP/SSE 归一逻辑；请求侧补齐 Pixcake 必需的客户端身份。
这不是 TS Agent Scope 管理平台的 ``/mcp/`` 协议。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any, cast
from uuid import uuid4

from .base import (
    DriverCapabilities,
    DriverEvent,
    DriverEventType,
    DriverPrepareContext,
    DriverSession,
)
from .http_sse import HttpSseDriver

_DEVICE_OS_VALUES = {"iOS", "Android", "Windows", "macOS", "Web"}
_CHAT_CHANNEL_VALUES = {"pixcake_client", "pixcake_wechat"}
_PROTECTED_REQUEST_FIELDS = {
    "type",
    "message",
    "session_id",
    "tool_results",
    "user_id",
    "device_info",
    "chat_channel",
}


class PixcakeHttpSseDriver(HttpSseDriver):
    """把 AgentRig Driver 契约映射到 Pixcake ChatRequest。"""

    def capabilities(self) -> DriverCapabilities:
        # 当前 Pixcake 协议支持平台观察工具调用并回灌结果，但不会读取
        # 通用 ``tool_proxy`` 字段，也没有稳定的 usage 事件。
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
        )

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        session = await super().prepare(context)
        options = dict(context.target.get("options") or {})
        user_id = options.get("user_id")
        if type(user_id) is not int:
            raise ValueError("pixcake_http_sse target options.user_id must be an integer")

        device_info = options.get("device_info")
        self._validate_device_info(device_info)
        chat_channel = options.get("chat_channel", "pixcake_client")
        if chat_channel not in _CHAT_CHANNEL_VALUES:
            raise ValueError(
                "pixcake_http_sse target options.chat_channel must be "
                "pixcake_client or pixcake_wechat"
            )

        request_defaults = options.get("request_defaults", {})
        if not isinstance(request_defaults, dict):
            raise ValueError(
                "pixcake_http_sse target options.request_defaults must be an object"
            )
        case_request = context.initial_state.get("pixcake_request", {})
        if not isinstance(case_request, dict):
            raise ValueError("case initial_state.pixcake_request must be an object")

        merged_request_defaults = {
            **self._without_protected_fields(request_defaults),
            **self._without_protected_fields(case_request),
        }
        # AgentScope 只在新会话的第一条消息发送初始附件；后续轮次沿用
        # session_id 和 metadata。重复附件会被 Pixcake 当作本轮新附件。
        initial_request_fields: dict[str, Any] = {}
        if "attachments" in merged_request_defaults:
            initial_request_fields["attachments"] = merged_request_defaults.pop(
                "attachments"
            )

        session.state.update(
            {
                "user_id": user_id,
                "device_info": dict(cast("dict[str, Any]", device_info)),
                "chat_channel": chat_channel,
                "request_defaults": merged_request_defaults,
                "initial_request_fields": initial_request_fields,
            }
        )
        session.state["headers"].setdefault("Accept", "text/event-stream")
        return session

    @staticmethod
    def _validate_device_info(value: object) -> None:
        if not isinstance(value, dict):
            raise ValueError(
                "pixcake_http_sse target options.device_info must be an object"
            )
        required_strings = ("os", "os_version", "app_version")
        missing = [
            name
            for name in required_strings
            if not isinstance(value.get(name), str) or not value[name]
        ]
        if missing:
            raise ValueError(
                "pixcake_http_sse target options.device_info requires non-empty "
                f"strings: {', '.join(missing)}"
            )
        if value["os"] not in _DEVICE_OS_VALUES:
            raise ValueError(
                "pixcake_http_sse target options.device_info.os is unsupported"
            )
        tool_version = value.get("tool_version")
        if tool_version is not None and type(tool_version) is not int:
            raise ValueError(
                "pixcake_http_sse target options.device_info.tool_version "
                "must be an integer"
            )

    @staticmethod
    def _without_protected_fields(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item
            for key, item in value.items()
            if key not in _PROTECTED_REQUEST_FIELDS
        }

    @staticmethod
    def _add_shared_payload(
        session: DriverSession,
        payload: dict[str, Any],
    ) -> None:
        if payload.get("type") == "chat":
            payload.update(session.state["request_defaults"])
            if not session.state.get("session_id"):
                payload.update(session.state["initial_request_fields"])
        if session.state.get("session_id"):
            payload["session_id"] = session.state["session_id"]
        payload["user_id"] = session.state["user_id"]
        payload["device_info"] = session.state["device_info"]
        payload["chat_channel"] = session.state["chat_channel"]

    async def _post(
        self,
        session: DriverSession,
        payload: dict[str, Any],
    ) -> AsyncIterator[DriverEvent]:
        request_id = str(uuid4())
        request_kind = str(payload.get("type") or "unknown")
        session.state["headers"]["X-Request-Id"] = request_id
        started = perf_counter()
        ttft_ms: float | None = None
        yield DriverEvent(
            type=DriverEventType.REQUEST_STARTED,
            request_id=request_id,
            request_kind=request_kind,
        )
        try:
            async for event in super()._post(session, payload):
                if (
                    ttft_ms is None
                    and event.type
                    in {
                        DriverEventType.ASSISTANT_TEXT_DELTA,
                        DriverEventType.ASSISTANT_MESSAGE_COMPLETED,
                        DriverEventType.TOOL_CALLS,
                        DriverEventType.ERROR,
                    }
                ):
                    ttft_ms = (perf_counter() - started) * 1000
                yield event.model_copy(update={"request_id": request_id})
        except Exception:
            yield DriverEvent(
                type=DriverEventType.REQUEST_COMPLETED,
                request_id=request_id,
                request_kind=request_kind,
                request_status="failed",
                duration_ms=(perf_counter() - started) * 1000,
                ttft_ms=ttft_ms,
            )
            raise
        yield DriverEvent(
            type=DriverEventType.REQUEST_COMPLETED,
            request_id=request_id,
            request_kind=request_kind,
            request_status="completed",
            duration_ms=(perf_counter() - started) * 1000,
            ttft_ms=ttft_ms,
        )
