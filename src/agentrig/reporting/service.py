"""基于完整分页生成报告，并复用统一 Redactor 生成安全导出。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Literal, NoReturn

from ..cases.repository import CaseRepository
from ..cases.schemas import CaseSelector, TestCasePage, TestCaseView
from ..errors import AgentRigError, ErrorCode
from ..evaluations.models import EvaluationOutcome
from ..runs.models import RunStatus
from ..runs.redactor import Redactor
from ..runs.repository import RunRepository
from ..runs.schemas import CaseRunSummary, RunPage, RunView
from ..targets.repository import TargetRepository
from ..targets.schemas import TargetView
from ..tool_results.repository import SampleRepository
from ..tool_results.schemas import SamplePage, SampleView
from .schemas import (
    ExportCounts,
    RunOutcomeCounts,
    RunReport,
    RunReportFailure,
    RunReportRun,
    RunReportTarget,
    TargetExportBundle,
    TargetExportPreview,
    TargetExportScope,
)

ExportFormat = Literal["json", "markdown", "html"]


@dataclass(frozen=True)
class RenderedDocument:
    content: str
    media_type: str
    filename: str


class ReportingService:
    def __init__(
        self,
        *,
        cases: CaseRepository,
        targets: TargetRepository,
        samples: SampleRepository,
        runs: RunRepository,
        redactor: Redactor,
        max_report_case_runs: int,
        max_export_records: int,
    ) -> None:
        self._cases = cases
        self._targets = targets
        self._samples = samples
        self._runs = runs
        self._redactor = redactor
        self._max_report_case_runs = max_report_case_runs
        self._max_export_records = max_export_records

    async def run_report(self, run_id: str) -> RunReport:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"run not found: {run_id}",
                details={"run_id": run_id},
            )
        case_runs = await self._all_case_runs(run_id)
        counts = Counter(item.evaluation_state for item in case_runs)
        failures = [
            self._report_failure(item)
            for item in case_runs
            if item.evaluation_state is EvaluationOutcome.FAIL
            or item.error_code is not None
        ]
        evaluated = sum(
            counts[outcome]
            for outcome in (
                EvaluationOutcome.PASS,
                EvaluationOutcome.FAIL,
                EvaluationOutcome.INCONCLUSIVE,
            )
        )
        return RunReport(
            generated_at=datetime.now(timezone.utc),
            run=RunReportRun.model_validate(
                run.model_dump(exclude={"selection_snapshot", "profile_snapshot", "target_snapshots"})
            ),
            targets=[self._report_target(item) for item in run.target_snapshots],
            outcomes=RunOutcomeCounts(
                total=len(case_runs),
                evaluated=evaluated,
                pass_count=counts[EvaluationOutcome.PASS],
                fail_count=counts[EvaluationOutcome.FAIL],
                inconclusive_count=counts[EvaluationOutcome.INCONCLUSIVE],
                awaiting_verdict_count=counts[EvaluationOutcome.AWAITING_VERDICT],
                evaluation_error_count=counts[EvaluationOutcome.EVALUATION_ERROR],
            ),
            failures=failures,
        )

    async def export_preview(self, target_id: str) -> TargetExportPreview:
        await self._require_target(target_id)
        run_page = await self._runs.list_runs(target_id=target_id, limit=1, offset=0)
        case_page = await self._cases.list_page(CaseSelector(), limit=1, offset=0)
        sample_page = await self._samples.list_page(
            status=None,
            tool_name=None,
            limit=1,
            offset=0,
        )
        counts = self._export_counts(
            runs=run_page.total,
            test_cases=case_page.total,
            samples=sample_page.total,
        )
        return TargetExportPreview(
            target_id=target_id,
            counts=counts,
            max_export_records=self._max_export_records,
            within_limit=counts.total_records <= self._max_export_records,
        )

    async def target_export(self, target_id: str) -> TargetExportBundle:
        target = await self._require_target(target_id)
        first_runs = await self._runs.list_runs(
            target_id=target_id,
            limit=200,
            offset=0,
        )
        first_cases = await self._cases.list_page(
            CaseSelector(),
            limit=200,
            offset=0,
        )
        first_samples = await self._samples.list_page(
            status=None,
            tool_name=None,
            limit=200,
            offset=0,
        )
        counts = self._export_counts(
            runs=first_runs.total,
            test_cases=first_cases.total,
            samples=first_samples.total,
        )
        if counts.total_records > self._max_export_records:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "export exceeds the deployment record limit",
                details={
                    "record_count": counts.total_records,
                    "max_export_records": self._max_export_records,
                },
            )
        runs = await self._all_runs(target_id, first_runs)
        cases = await self._all_cases(first_cases)
        samples = await self._all_samples(first_samples)
        return TargetExportBundle(
            target_id=target_id,
            generated_at=datetime.now(timezone.utc),
            target=self._redactor.redact(target.model_dump(mode="json")),
            counts=counts,
            scope=TargetExportScope(
                runs=[self._redactor.redact(item.model_dump(mode="json")) for item in runs],
                test_cases=[
                    self._redactor.redact(item.model_dump(mode="json")) for item in cases
                ],
                samples=[
                    self._redactor.redact(item.model_dump(mode="json"))
                    for item in samples
                ],
            ),
            redaction=(
                "AgentRig unified evidence redaction applied; secret references are "
                "retained but resolved secret values are never exported"
            ),
        )

    def render_run_report(self, report: RunReport) -> RenderedDocument:
        if report.run.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "a downloadable report is available only after the run reaches a terminal state",
                details={"run_id": report.run.id, "status": report.run.status.value},
                retryable=True,
            )
        target_label = " / ".join(
            f"{item.name} ({item.version})" if item.version else item.name
            for item in report.targets
        ) or "Unknown Target"
        outcomes = report.outcomes
        failures = [
            (
                f"- **{self._markdown(item.case_id)}** — "
                f"{self._markdown(item.error_message or item.evaluation_summary or item.evaluation_state.value)}"
            )
            for item in report.failures
        ] or ["无失败或执行错误。"]
        content = "\n".join(
            [
                f"# {self._markdown(target_label)} 评测报告",
                "",
                f"- 运行编号：`{self._markdown(report.run.id)}`",
                f"- 执行状态：{report.run.status.value}",
                f"- 生成时间：{report.generated_at.isoformat()}",
                f"- 已评测：{outcomes.evaluated}",
                (
                    "- 通过 / 未通过 / 证据不足："
                    f"{outcomes.pass_count} / {outcomes.fail_count} / "
                    f"{outcomes.inconclusive_count}"
                ),
                f"- 执行错误：{report.run.failed_count}",
                "",
                "## 执行范围",
                "",
                *[f"- `{self._markdown(item)}`" for item in report.run.resolved_case_ids],
                "",
                "## 主要失败",
                "",
                *failures,
                "",
                "> 根据 AgentRig 不可变运行事实生成。",
            ]
        )
        return RenderedDocument(
            content=content,
            media_type="text/markdown; charset=utf-8",
            filename=f"agentrig-{self._filename(report.run.id)}-report.md",
        )

    def render_target_export(
        self,
        bundle: TargetExportBundle,
        export_format: ExportFormat,
    ) -> RenderedDocument:
        stem = f"agentrig-{self._filename(bundle.target_id)}-export"
        if export_format == "json":
            return RenderedDocument(
                content=bundle.model_dump_json(indent=2),
                media_type="application/json",
                filename=f"{stem}.json",
            )
        if export_format == "markdown":
            return RenderedDocument(
                content=self._export_markdown(bundle),
                media_type="text/markdown; charset=utf-8",
                filename=f"{stem}.md",
            )
        return RenderedDocument(
            content=self._export_html(bundle),
            media_type="text/html; charset=utf-8",
            filename=f"{stem}.html",
        )

    async def _all_case_runs(self, run_id: str) -> list[CaseRunSummary]:
        first = await self._runs.list_case_runs(run_id, limit=200, offset=0)
        if first.total > self._max_report_case_runs:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "run report exceeds the deployment CaseRun limit",
                details={
                    "case_run_count": first.total,
                    "max_report_case_runs": self._max_report_case_runs,
                },
            )
        items = list(first.items)
        while len(items) < first.total:
            page = await self._runs.list_case_runs(
                run_id,
                limit=200,
                offset=len(items),
            )
            self._require_same_total(first.total, page.total, "run report")
            if not page.items:
                self._changed_during_generation("run report")
            items.extend(page.items)
        self._require_complete(items, first.total, "run report")
        return items

    async def _all_runs(self, target_id: str, first: RunPage) -> list[RunView]:
        items = list(first.items)
        expected = first.total
        while len(items) < expected:
            current = await self._runs.list_runs(
                target_id=target_id,
                limit=200,
                offset=len(items),
            )
            self._require_same_total(expected, current.total, "target export")
            if not current.items:
                self._changed_during_generation("target export")
            items.extend(current.items)
        self._require_complete(items, expected, "target export")
        return items

    async def _all_cases(self, first: TestCasePage) -> list[TestCaseView]:
        items = list(first.items)
        expected = first.total
        while len(items) < expected:
            current = await self._cases.list_page(
                CaseSelector(),
                limit=200,
                offset=len(items),
            )
            self._require_same_total(expected, current.total, "target export")
            if not current.items:
                self._changed_during_generation("target export")
            items.extend(current.items)
        self._require_complete(items, expected, "target export")
        return items

    async def _all_samples(self, first: SamplePage) -> list[SampleView]:
        items = list(first.items)
        expected = first.total
        while len(items) < expected:
            current = await self._samples.list_page(
                status=None,
                tool_name=None,
                limit=200,
                offset=len(items),
            )
            self._require_same_total(expected, current.total, "target export")
            if not current.items:
                self._changed_during_generation("target export")
            items.extend(current.items)
        self._require_complete(items, expected, "target export")
        return items

    async def _require_target(self, target_id: str) -> TargetView:
        target = await self._targets.get(target_id)
        if target is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"target not found: {target_id}",
                details={"target_id": target_id},
            )
        return target

    @staticmethod
    def _export_counts(*, runs: int, test_cases: int, samples: int) -> ExportCounts:
        return ExportCounts(
            runs=runs,
            test_cases=test_cases,
            samples=samples,
            total_records=runs + test_cases + samples,
        )

    @staticmethod
    def _report_target(value: dict[str, object]) -> RunReportTarget:
        return RunReportTarget(
            id=str(value.get("id") or "inline_target"),
            name=str(value.get("name") or value.get("id") or "Unknown Target"),
            version=str(value["version"]) if value.get("version") is not None else None,
        )

    @staticmethod
    def _report_failure(value: CaseRunSummary) -> RunReportFailure:
        raw_summary = value.summary.get("evaluation_summary")
        return RunReportFailure(
            id=value.id,
            case_id=value.case_id,
            version=value.version,
            repeat_index=value.repeat_index,
            status=value.status,
            evaluation_state=value.evaluation_state,
            error_code=value.error_code,
            error_message=value.error_message,
            evaluation_summary=str(raw_summary) if raw_summary is not None else None,
        )

    @staticmethod
    def _require_same_total(expected: int, current: int, operation: str) -> None:
        if expected != current:
            ReportingService._changed_during_generation(operation)

    @staticmethod
    def _require_complete(items: Sequence[object], expected: int, operation: str) -> None:
        identifiers = [str(getattr(item, "id")) for item in items]
        if len(items) != expected or len(set(identifiers)) != expected:
            ReportingService._changed_during_generation(operation)

    @staticmethod
    def _changed_during_generation(operation: str) -> NoReturn:
        raise AgentRigError(
            ErrorCode.CONFLICT,
            f"data changed while generating {operation}; retry the request",
            retryable=True,
        )

    @staticmethod
    def _filename(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
        return cleaned[:96] or "data"

    @staticmethod
    def _markdown(value: object) -> str:
        return str(value).replace("`", "\\`").replace("\r", " ").replace("\n", " ")

    def _export_markdown(self, bundle: TargetExportBundle) -> str:
        target_name = self._markdown(bundle.target.get("name") or bundle.target_id)
        return "\n".join(
            [
                "# AgentRig 证据导出",
                "",
                f"- 被测 Agent：`{self._markdown(bundle.target_id)}` · {target_name}",
                f"- 生成时间：{bundle.generated_at.isoformat()}",
                f"- 运行：{bundle.counts.runs}",
                f"- 测试用例：{bundle.counts.test_cases}",
                f"- 结果样本：{bundle.counts.samples}",
                f"- 脱敏策略：{self._markdown(bundle.redaction)}",
                "",
                "## 评测运行",
                "",
                *[
                    f"- `{self._markdown(item.get('id'))}` · {self._markdown(item.get('status'))}"
                    for item in bundle.scope.runs
                ],
                "",
                "## 测试用例",
                "",
                *[
                    f"- `{self._markdown(item.get('id'))}` · {self._markdown(item.get('name'))}"
                    for item in bundle.scope.test_cases
                ],
                "",
                "## 结果样本",
                "",
                *[
                    f"- `{self._markdown(item.get('id'))}` · {self._markdown(item.get('name'))}"
                    for item in bundle.scope.samples
                ],
            ]
        )

    @staticmethod
    def _export_html(bundle: TargetExportBundle) -> str:
        def rows(items: list[dict[str, object]]) -> str:
            return "".join(
                "<li><code>"
                f"{escape(str(item.get('id') or ''))}</code> · "
                f"{escape(str(item.get('name') or item.get('status') or ''))}</li>"
                for item in items
            )

        return (
            "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
            "<title>AgentRig 证据导出</title>"
            "<style>body{max-width:960px;margin:40px auto;font:14px system-ui;"
            "color:#1b1d1c}code{background:#f1f3f2;padding:2px 4px}</style><body>"
            "<h1>AgentRig 证据导出</h1>"
            f"<p>被测 Agent：<code>{escape(bundle.target_id)}</code></p>"
            f"<p>生成时间：{escape(bundle.generated_at.isoformat())}</p>"
            f"<p>记录数量：{bundle.counts.total_records}</p>"
            f"<h2>评测运行</h2><ul>{rows(bundle.scope.runs)}</ul>"
            f"<h2>测试用例</h2><ul>{rows(bundle.scope.test_cases)}</ul>"
            f"<h2>结果样本</h2><ul>{rows(bundle.scope.samples)}</ul>"
            f"<p>{escape(bundle.redaction)}</p></body></html>"
        )
