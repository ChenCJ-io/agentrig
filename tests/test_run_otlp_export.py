from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from agentrig.config import RunOtlpExportConfig
from agentrig.observability import RunOtlpExporter
from agentrig.runs.models import RunStatus
from agentrig.runs.scheduler import RunScheduler
from agentrig.runs.schemas import RunView

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _run(status: RunStatus = RunStatus.COMPLETED) -> RunView:
    return RunView(
        id="run_export",
        status=status,
        selection_snapshot={"prompt": "must-not-be-exported"},
        resolved_case_ids=["case_secret"],
        profile_snapshot={"secret": "must-not-be-exported"},
        target_snapshots=[{"authorization": "must-not-be-exported"}],
        total_count=2,
        completed_count=1,
        failed_count=1,
        skipped_count=0,
        cancelled_count=0,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=2),
        error_code=None,
        error_message="must-not-be-exported",
    )


async def test_run_otlp_export_is_protobuf_and_metadata_only() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    exporter = RunOtlpExporter(
        RunOtlpExportConfig(
            enabled=True,
            endpoint="https://collector.example/v1/traces",
            service_name="agentrig-test",
        ),
        headers={"X-Collector-Key": "header-secret"},
        transport=httpx.MockTransport(handler),
    )
    await exporter(_run())

    assert len(captured) == 1
    assert captured[0].headers["content-type"] == "application/x-protobuf"
    assert captured[0].headers["x-collector-key"] == "header-secret"
    request = trace_service_pb2.ExportTraceServiceRequest()
    request.ParseFromString(captured[0].content)
    span = request.resource_spans[0].scope_spans[0].spans[0]
    values = {
        item.key: (
            item.value.string_value
            if item.value.WhichOneof("value") == "string_value"
            else item.value.int_value
        )
        for item in span.attributes
    }
    assert values["agentrig.run.id"] == "run_export"
    assert values["agentrig.run.failed_count"] == 1
    serialized = str(request).casefold()
    assert "must-not-be-exported" not in serialized
    assert "header-secret" not in serialized


class _RunRepository:
    def __init__(self) -> None:
        self.run = _run(RunStatus.QUEUED)

    async def set_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        assert run_id == self.run.id
        self.run = self.run.model_copy(
            update={
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
            }
        )

    async def refresh_run_counts(self, run_id: str) -> RunView:
        assert run_id == self.run.id
        return self.run

    async def get_run(self, run_id: str) -> RunView | None:
        return self.run if run_id == self.run.id else None


class _UnusedExecutor:
    async def execute(self, case_run_id: str, cancel_event: Any) -> None:
        raise AssertionError((case_run_id, cancel_event))


async def test_collector_failure_cannot_change_terminal_run_state() -> None:
    async def unavailable(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    repository = _RunRepository()
    scheduler = RunScheduler(repository, _UnusedExecutor())  # type: ignore[arg-type]
    scheduler.add_completion_listener(
        RunOtlpExporter(
            RunOtlpExportConfig(
                enabled=True,
                endpoint="https://collector.example/v1/traces",
            ),
            transport=httpx.MockTransport(unavailable),
        )
    )
    scheduler.submit("run_export", [], concurrency=1)
    await scheduler.wait("run_export")

    assert repository.run.status is RunStatus.COMPLETED
