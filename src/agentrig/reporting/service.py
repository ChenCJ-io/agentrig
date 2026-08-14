"""基于完整分页生成报告，并复用统一 Redactor 生成安全导出。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import TYPE_CHECKING, Literal, NoReturn

from ..cases.repository import CaseRepository
from ..cases.schemas import CaseSelector, TestCasePage, TestCaseView
from ..errors import AgentRigError, ErrorCode
from ..evaluations.models import EvaluationOutcome
from ..runs.models import RunStatus
from ..runs.redactor import Redactor
from ..runs.repository import RunRepository
from ..runs.schemas import CaseRunDetail, CaseRunSummary, RunPage, RunView
from ..targets.repository import TargetRepository
from ..targets.schemas import TargetView
from ..tool_results.repository import SampleRepository
from ..tool_results.schemas import SamplePage, SampleView
from .quality import (
    build_comparison_report,
    build_quality_report,
    source_snapshot_hash,
)
from .recovery import apply_recovery_overlay
from .schemas import (
    ComparisonReport,
    ExportCounts,
    QualityReport,
    RecoveryProvenance,
    RunOutcomeCounts,
    RunReport,
    RunReportFailure,
    RunReportRun,
    RunReportTarget,
    TargetExportBundle,
    TargetExportPreview,
    TargetExportScope,
)

if TYPE_CHECKING:
    from ..agents.invocation_schemas import AgentInvocationView
    from ..agents.invocation_service import AgentInvocationService
    from ..assistant.decision_schemas import DecisionRecordView
    from ..assistant.decision_service import DecisionService

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
        decisions: DecisionService | None = None,
        invocations: AgentInvocationService | None = None,
    ) -> None:
        self._cases = cases
        self._targets = targets
        self._samples = samples
        self._runs = runs
        self._redactor = redactor
        self._max_report_case_runs = max_report_case_runs
        self._max_export_records = max_export_records
        self._decisions = decisions
        self._invocations = invocations

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

    async def quality_report(self, run_id: str) -> QualityReport:
        run, case_runs, decisions, invocations, recovery_runs, recovery = (
            await self._stable_report_inputs(run_id)
        )
        return build_quality_report(
            run,
            case_runs,
            decisions,
            invocations,
            recovery_runs,
            recovery,
        )

    async def comparison_report(self, run_id: str) -> ComparisonReport:
        run, case_runs, decisions, invocations, recovery_runs, recovery = (
            await self._stable_report_inputs(run_id)
        )
        if not any(item.comparison_pair_id is not None for item in case_runs):
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "comparison report requires an A/B run",
                details={"run_id": run_id},
            )
        return build_comparison_report(
            run,
            case_runs,
            decisions,
            invocations,
            recovery_runs,
            recovery,
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

    def render_quality_report(self, report: QualityReport) -> RenderedDocument:
        content = "\n".join(
            [
                "# AgentRig 质量报告",
                "",
                f"- 运行编号：`{self._markdown(report.run_id)}`",
                f"- 执行状态：{report.run_status.value}",
                f"- 来源快照：`{report.source_snapshot_hash}`",
                f"- 生成时间：{report.generated_at.isoformat()}",
                "",
                "## 结果",
                "",
                (
                    "- 通过 / 未通过 / 证据不足 / 评测错误："
                    f"{report.outcomes.pass_count} / {report.outcomes.fail_count} / "
                    f"{report.outcomes.inconclusive_count} / "
                    f"{report.outcomes.evaluation_error_count}"
                ),
                (
                    "- 跳过 / 取消 / 中断 / 执行失败："
                    f"{report.outcomes.skipped_count} / "
                    f"{report.outcomes.cancelled_count} / "
                    f"{report.outcomes.interrupted_count} / "
                    f"{report.outcomes.execution_failed_count}"
                ),
                "",
                "## 性能与用量",
                "",
                f"- Run 耗时：{self._display_number(report.latency.run_duration_ms, ' ms')}",
                f"- CaseRun p50：{self._display_number(report.latency.case_run.p50_ms, ' ms')}",
                f"- CaseRun p95：{self._display_number(report.latency.case_run.p95_ms, ' ms')}",
                f"- TTFT p50：{self._display_number(report.latency.ttft.p50_ms, ' ms')}",
                f"- 总 Token：{self._display_number(report.usage.total_tokens)}",
                "",
                "## 证据质量",
                "",
                (
                    "- 有效 / 外部 / 缺失引用："
                    f"{report.evidence_quality.valid_reference_count} / "
                    f"{report.evidence_quality.foreign_reference_count} / "
                    f"{report.evidence_quality.missing_reference_count}"
                ),
                (
                    "- 引用有效率："
                    f"{self._display_ratio(report.evidence_quality.reference_validity_rate)}"
                ),
                "",
                "## 已知限制",
                "",
                *(
                    [f"- `{self._markdown(item)}`" for item in report.limitations]
                    or ["- 无。"]
                ),
            ]
        )
        return RenderedDocument(
            content=content,
            media_type="text/markdown; charset=utf-8",
            filename=f"agentrig-{self._filename(report.run_id)}-quality.md",
        )

    def render_comparison_report(self, report: ComparisonReport) -> RenderedDocument:
        pair_lines = [
            (
                f"- `{self._markdown(item.comparison_pair_id)}` · "
                f"`{self._markdown(item.case_id)}` · {item.classification}"
            )
            for item in report.pairs
        ] or ["- 无配对。"]
        content = "\n".join(
            [
                "# AgentRig A/B 对比报告",
                "",
                f"- 运行编号：`{self._markdown(report.run_id)}`",
                f"- 来源快照：`{report.source_snapshot_hash}`",
                f"- 总配对 / 可比较：{report.summary.total_pairs} / {report.summary.comparable_pairs}",
                f"- 回归 / 修复：{report.summary.regression_count} / {report.summary.fix_count}",
                (
                    "- 基础设施错误 / 配对不完整："
                    f"{report.summary.infrastructure_error_count} / "
                    f"{report.summary.incomplete_pair_count}"
                ),
                "",
                "## 聚合变化",
                "",
                (
                    "- 耗时变化："
                    f"{self._display_ratio(report.metrics.duration_regression_ratio)} "
                    f"（{report.metrics.duration_sample_count} 对）"
                ),
                (
                    "- Token 变化："
                    f"{self._display_ratio(report.metrics.token_regression_ratio)} "
                    f"（{report.metrics.token_sample_count} 对）"
                ),
                "",
                "## 配对",
                "",
                *pair_lines,
                "",
                "## 已知限制",
                "",
                *(
                    [f"- `{self._markdown(item)}`" for item in report.limitations]
                    or ["- 无。"]
                ),
            ]
        )
        return RenderedDocument(
            content=content,
            media_type="text/markdown; charset=utf-8",
            filename=f"agentrig-{self._filename(report.run_id)}-comparison.md",
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

    async def _all_case_run_details(self, run_id: str) -> list[CaseRunDetail]:
        summaries = await self._all_case_runs(run_id)
        details: list[CaseRunDetail] = []
        for summary in summaries:
            detail = await self._runs.get_case_run(summary.id)
            if detail is None or detail.run_id != run_id:
                self._changed_during_generation("quality report")
            details.append(detail)
        return details

    async def _all_invocations(self, run_id: str) -> list[AgentInvocationView]:
        if self._invocations is None:
            return []
        first = await self._invocations.list_for_run(run_id, limit=200, offset=0)
        items = list(first.items)
        while len(items) < first.total:
            page = await self._invocations.list_for_run(
                run_id,
                limit=200,
                offset=len(items),
            )
            self._require_same_total(first.total, page.total, "quality report invocations")
            if not page.items:
                self._changed_during_generation("quality report invocations")
            items.extend(page.items)
        self._require_complete(items, first.total, "quality report invocations")
        return items

    async def _stable_report_inputs(
        self,
        run_id: str,
    ) -> tuple[
        RunView,
        list[CaseRunDetail],
        list[DecisionRecordView],
        list[AgentInvocationView],
        list[RunView],
        RecoveryProvenance,
    ]:
        first = await self._read_report_inputs(run_id)
        second = await self._read_report_inputs(run_id)
        first_hash = source_snapshot_hash(
            first[0],
            first[1],
            first[2],
            first[3],
            first[4],
        )
        second_hash = source_snapshot_hash(
            second[0],
            second[1],
            second[2],
            second[3],
            second[4],
        )
        if first_hash != second_hash:
            self._changed_during_generation("quality report")
        return second

    async def _read_report_inputs(
        self,
        run_id: str,
    ) -> tuple[
        RunView,
        list[CaseRunDetail],
        list[DecisionRecordView],
        list[AgentInvocationView],
        list[RunView],
        RecoveryProvenance,
    ]:
        run = await self._runs.get_run(run_id)
        if run is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"run not found: {run_id}",
                details={"run_id": run_id},
            )
        if run.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "quality and comparison reports require a terminal run",
                details={"run_id": run_id, "status": run.status.value},
                retryable=True,
            )
        source_case_runs = await self._all_case_run_details(run_id)
        recovery_runs = await self._all_recovery_runs(run_id)
        terminal_recovery_runs = [
            item
            for item in recovery_runs
            if item.status
            in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
                RunStatus.FAILED,
            }
        ]
        recovery_case_runs: list[CaseRunDetail] = []
        for recovery_run in terminal_recovery_runs:
            recovery_case_runs.extend(
                await self._all_case_run_details(recovery_run.id)
            )
        overlay = apply_recovery_overlay(
            run,
            source_case_runs,
            recovery_runs,
            recovery_case_runs,
        )
        report_run_ids = [run_id, *(item.id for item in terminal_recovery_runs)]
        decisions: list[DecisionRecordView] = []
        if self._decisions is not None:
            for report_run_id in report_run_ids:
                decisions.extend(
                    (await self._decisions.list_for_run(report_run_id)).items
                )
        invocations: list[AgentInvocationView] = []
        for report_run_id in report_run_ids:
            invocations.extend(await self._all_invocations(report_run_id))
        return (
            run,
            list(overlay.effective_case_runs),
            decisions,
            invocations,
            list(overlay.recovery_runs),
            overlay.provenance,
        )

    async def _all_recovery_runs(self, source_run_id: str) -> list[RunView]:
        list_recovery_runs = getattr(self._runs, "list_recovery_runs", None)
        if list_recovery_runs is None:
            return []
        discovered: list[RunView] = []
        pending = [source_run_id]
        seen = {source_run_id}
        while pending:
            parent_id = pending.pop(0)
            first = await list_recovery_runs(parent_id, limit=200, offset=0)
            children = list(first.items)
            while len(children) < first.total:
                page = await list_recovery_runs(
                    parent_id,
                    limit=200,
                    offset=len(children),
                )
                self._require_same_total(
                    first.total,
                    page.total,
                    "quality report recovery lineage",
                )
                if not page.items:
                    self._changed_during_generation(
                        "quality report recovery lineage"
                    )
                children.extend(page.items)
            self._require_complete(
                children,
                first.total,
                "quality report recovery lineage",
            )
            for child in children:
                if child.id in seen:
                    continue
                seen.add(child.id)
                discovered.append(child)
                pending.append(child.id)
                if len(discovered) > self._max_report_case_runs:
                    raise AgentRigError(
                        ErrorCode.VALIDATION_ERROR,
                        "recovery lineage exceeds the deployment report limit",
                        details={
                            "recovery_run_count": len(discovered),
                            "max_report_case_runs": self._max_report_case_runs,
                        },
                    )
        return sorted(discovered, key=lambda item: (item.created_at, item.id))

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

    @staticmethod
    def _display_number(value: object, suffix: str = "") -> str:
        return "不可用" if value is None else f"{value}{suffix}"

    @staticmethod
    def _display_ratio(value: float | None) -> str:
        return "不可用" if value is None else f"{value * 100:.2f}%"

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
