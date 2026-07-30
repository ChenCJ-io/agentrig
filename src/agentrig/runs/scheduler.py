"""单进程 asyncio Scheduler。"""

from __future__ import annotations

import asyncio

from .executor import CaseExecutor
from .models import CaseRunStatus, RunStatus
from .repository import RunRepository


class RunScheduler:
    def __init__(self, runs: RunRepository, executor: CaseExecutor) -> None:
        self._runs = runs
        self._executor = executor
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def submit(
        self,
        run_id: str,
        case_run_ids: list[str],
        *,
        concurrency: int,
    ) -> None:
        if run_id in self._tasks:
            raise RuntimeError(f"run already scheduled: {run_id}")
        cancel_event = asyncio.Event()
        task = asyncio.create_task(
            self._run(
                run_id,
                case_run_ids,
                concurrency=concurrency,
                cancel_event=cancel_event,
            ),
            name=f"agentrig:{run_id}",
        )
        self._cancel_events[run_id] = cancel_event
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._cleanup(run_id))

    async def cancel(self, run_id: str) -> bool:
        event = self._cancel_events.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    async def wait(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._runs.mark_in_progress_interrupted()

    async def _run(
        self,
        run_id: str,
        case_run_ids: list[str],
        *,
        concurrency: int,
        cancel_event: asyncio.Event,
    ) -> None:
        try:
            await self._runs.set_run_status(run_id, RunStatus.RUNNING)
            semaphore = asyncio.Semaphore(concurrency)

            async def execute_one(case_run_id: str) -> None:
                async with semaphore:
                    if cancel_event.is_set():
                        await self._runs.set_case_run_status(
                            case_run_id,
                            CaseRunStatus.CANCELLED,
                            error_code="cancelled",
                            error_message="run cancelled before case execution started",
                        )
                        return
                    await self._executor.execute(case_run_id, cancel_event)
                    await self._runs.refresh_run_counts(run_id)

            await asyncio.gather(*(execute_one(item) for item in case_run_ids))
            await self._runs.refresh_run_counts(run_id)
            await self._runs.set_run_status(
                run_id,
                RunStatus.CANCELLED if cancel_event.is_set() else RunStatus.COMPLETED,
            )
        except Exception as exc:
            await self._runs.set_run_status(
                run_id,
                RunStatus.FAILED,
                error_code="internal_error",
                error_message=str(exc),
            )

    def _cleanup(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._cancel_events.pop(run_id, None)
