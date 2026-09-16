"""从 Real Tool 运行证据显式创建 Sample 草稿所需的读取器。"""

from __future__ import annotations

from sqlalchemy import select

from ..orm import RunEventORM
from ..session import Database


class SqlToolCallEvidenceReader:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def sample_source(self, tool_call_id: str) -> dict[str, object] | None:
        async with self._database.session() as session:
            call = await session.get(RunEventORM, tool_call_id)
            if call is None or call.event_type != "tool_call":
                return None
            results = list(
                await session.scalars(
                    select(RunEventORM)
                    .where(
                        RunEventORM.case_run_id == call.case_run_id,
                        RunEventORM.event_type == "tool_result",
                    )
                    .order_by(RunEventORM.seq)
                )
            )
        result = next(
            (
                item
                for item in results
                if item.payload.get("tool_call_event_id") == tool_call_id
                and item.payload.get("source") == "real_tool"
            ),
            None,
        )
        if result is None:
            return None
        return {
            "tool_name": str(call.payload["tool_name"]),
            "arguments": dict(call.payload.get("arguments") or {}),
            "result": result.payload.get("result"),
        }
