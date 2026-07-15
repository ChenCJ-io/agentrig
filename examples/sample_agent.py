"""Sample 被测 agent：两步 tool-calling（search → summarize）。

deterministic（不经 LLM），用于平台验收演示：一条用例覆盖**多轮 tool-calling
回路** + tool_call_order 断言。比 demo_agent（单步 echo）更有代表性。

决策：
- chat 且消息像查询（含 ?/search/查）→ 产出 tool_calls:[search]
- tool_result 回灌 search → 产出 tool_calls:[summarize]
- tool_result 回灌 summarize → text + done
- chat 非查询 → 直接 text + done

独立起::

    uvicorn examples.sample_agent:app --port 9003
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """streaming-chat 协议请求体。"""

    type: str
    message: str | None = None
    session_id: str | None = None
    tool_results: list[dict[str, object]] | None = None


app = FastAPI(title="agentrig-sample-agent")


def _sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _needs_search(message: str) -> bool:
    return "?" in message or "search" in message.lower() or "查" in message


async def _respond(req: ChatRequest) -> AsyncIterator[str]:
    session_id = req.session_id or f"sess-{uuid4().hex[:8]}"
    yield _sse({"type": "session_created", "run_id": "r1", "data": {"session_id": session_id}})

    if req.type == "tool_result":
        names = [str(r.get("name")) for r in (req.tool_results or [])]
        if "search" in names:
            # search 回灌完 → 调 summarize
            yield _sse(
                {
                    "type": "tool_calls",
                    "run_id": "r1",
                    "data": {
                        "tool_calls": [
                            {"id": "tc2", "type": "function", "name": "summarize",
                             "input": {"topic": "search-result"}}
                        ]
                    },
                }
            )
        elif "summarize" in names:
            # summarize 回灌完 → 结束
            yield _sse(
                {"type": "text_delta", "run_id": "r1", "data": {"text": "已为你搜索并总结。"}}
            )
            yield _sse({"type": "done", "run_id": "r1", "data": {"result": "completed"}})
        return

    # type == "chat"
    message = req.message or ""
    if _needs_search(message):
        yield _sse(
            {
                "type": "tool_calls",
                "run_id": "r1",
                "data": {
                    "tool_calls": [
                        {"id": "tc1", "type": "function", "name": "search",
                         "input": {"query": message}}
                    ]
                },
            }
        )
    else:
        yield _sse(
            {"type": "text_delta", "run_id": "r1", "data": {"text": f"你说的是：{message}"}}
        )
        yield _sse({"type": "done", "run_id": "r1", "data": {"result": "completed"}})


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(_respond(req), media_type="text/event-stream")
