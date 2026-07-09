"""Demo 被测 agent：最小 streaming-chat SSE agent（不经 LLM，deterministic）。

供 execution 真实模式 / 端到端测试用。复用 streaming-chat 协议契约
（POST /chat/stream，SSE 响应 `data: {type, run_id, data}`）。

决策规则（关键词路由，便于写确定性用例）：
- message 含 "echo"    → 产出 tool_calls:[echo]
- message 含 "reverse" → 产出 tool_calls:[reverse]
- 否则                 → 直接 text_delta + done

收到 type=tool_result 回灌后 → text_delta + done（结束本轮）。

独立起::

    uvicorn examples.demo_agent:app --port 9002
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """streaming-chat 协议请求体（type=chat 或 tool_result）。"""

    type: str
    message: str | None = None
    session_id: str | None = None
    tool_results: list[dict[str, object]] | None = None


app = FastAPI(title="agentrig-demo-agent")


def _sse(event: dict[str, object]) -> str:
    """序列化一个 SSE data: 行。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _respond(req: ChatRequest) -> AsyncIterator[str]:
    session_id = req.session_id or f"sess-{uuid4().hex[:8]}"
    # 首话给 session_created
    yield _sse({"type": "session_created", "run_id": "r1", "data": {"session_id": session_id}})

    if req.type == "tool_result":
        # 回灌确认后结束本轮
        yield _sse({"type": "text_delta", "run_id": "r1", "data": {"text": "ok"}})
        yield _sse({"type": "done", "run_id": "r1", "data": {"result": "completed"}})
        return

    # type == "chat"：按关键词决策调哪个工具
    message = req.message or ""
    if "echo" in message:
        tool = "echo"
    elif "reverse" in message:
        tool = "reverse"
    else:
        yield _sse(
            {"type": "text_delta", "run_id": "r1", "data": {"text": f"echo back: {message}"}}
        )
        yield _sse({"type": "done", "run_id": "r1", "data": {"result": "completed"}})
        return

    yield _sse(
        {
            "type": "tool_calls",
            "run_id": "r1",
            "data": {
                "tool_calls": [
                    {"id": "tc1", "type": "function", "name": tool, "input": {"text": message}}
                ]
            },
        }
    )
    # agent 产出 tool_calls 后结束本流；回灌走下一次 POST（type=tool_result 分支）。


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(_respond(req), media_type="text/event-stream")
