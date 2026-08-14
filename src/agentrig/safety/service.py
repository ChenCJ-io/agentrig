"""Runtime safety suite loading, report aggregation, and blocking gate."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib.resources import files
from typing import Literal

from ..canonical import canonical_hash
from ..errors import AgentRigError, ErrorCode
from ..runs.repository import RunRepository
from ..runs.schemas import CaseRunDetail
from .rules import evaluate_rule
from .schemas import (
    RuntimeSafetyReport,
    SafetyCaseResult,
    SafetyCaseSpec,
    SafetyDomainSummary,
    SafetyGateResult,
    SafetyRuleResult,
    SafetyStatus,
    SafetySuiteManifest,
)


def load_builtin_suite(
    suite_id: str = "agentscope-runtime-safety",
    version: str = "1.0.0",
) -> SafetySuiteManifest:
    if (suite_id, version) != ("agentscope-runtime-safety", "1.0.0"):
        raise AgentRigError(
            ErrorCode.NOT_FOUND,
            f"safety suite not found: {suite_id}@{version}",
        )
    resource = files("agentrig.safety").joinpath(
        "manifests/agentscope-runtime-safety-v1.json"
    )
    manifest = SafetySuiteManifest.model_validate_json(resource.read_text(encoding="utf-8"))
    source = manifest.model_dump(mode="json", exclude={"content_hash"})
    if canonical_hash(source) != manifest.content_hash:
        raise AgentRigError(
            ErrorCode.CONFLICT,
            "safety suite content hash does not match its immutable manifest",
        )
    return manifest


class SafetyService:
    def __init__(self, repository: RunRepository, *, max_case_runs: int = 10_000) -> None:
        self._repository = repository
        self._max_case_runs = max_case_runs

    async def report(
        self,
        run_id: str,
        *,
        suite_id: str = "agentscope-runtime-safety",
        version: str = "1.0.0",
    ) -> RuntimeSafetyReport:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise AgentRigError(ErrorCode.NOT_FOUND, f"run not found: {run_id}")
        manifest = load_builtin_suite(suite_id, version)
        details = await self._all_case_runs(run_id)
        by_case: dict[str, list[CaseRunDetail]] = defaultdict(list)
        for detail in details:
            by_case[detail.case_id].append(detail)
        results: list[SafetyCaseResult] = []
        for case in manifest.cases:
            matched = sorted(by_case.get(case.id, []), key=lambda item: item.id)
            if not matched:
                results.append(self._missing_case(case))
                continue
            results.extend(self._evaluate_case(case, detail) for detail in matched)
        domain_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for result in results:
            domain_counts[result.risk_domain][result.status] += 1
        unsupported = sorted(
            {
                capability
                for result in results
                if result.capability_status == "unsupported"
                for capability in self._case(manifest, result.case_id).required_capabilities
            }
        )
        unknown = sorted(
            {
                capability
                for result in results
                if result.capability_status in {"unknown", "not_observed"}
                for capability in self._case(manifest, result.case_id).required_capabilities
            }
        )
        failures = sorted(
            {
                result.case_id
                for result in results
                if result.status == "fail" and result.severity in {"critical", "high"}
            }
        )
        limitations: list[str] = []
        if unknown:
            limitations.append("required_capabilities_not_observed")
        if any(result.status == "skipped" for result in results):
            limitations.append("suite_cases_not_executed_or_unsupported")
        profile_kind = self._profile_kind(details)
        snapshot = {
            "run": run.model_dump(mode="json"),
            "suite": manifest.model_dump(mode="json"),
            "case_runs": [detail.model_dump(mode="json") for detail in details],
            "results": [result.model_dump(mode="json") for result in results],
        }
        return RuntimeSafetyReport(
            generated_at=datetime.now(timezone.utc),
            run_id=run_id,
            suite_id=manifest.id,
            suite_version=manifest.version,
            suite_content_hash=manifest.content_hash,
            source_snapshot_hash=canonical_hash(snapshot),
            profile_kind=profile_kind,
            domains=[
                SafetyDomainSummary(
                    risk_domain=domain,
                    total=sum(counts.values()),
                    pass_count=counts["pass"],
                    fail_count=counts["fail"],
                    inconclusive_count=counts["inconclusive"],
                    skipped_count=counts["skipped"],
                )
                for domain, counts in sorted(domain_counts.items())
            ],
            cases=results,
            critical_high_failures=failures,
            unsupported_capabilities=unsupported,
            unknown_capabilities=unknown,
            limitations=limitations,
        )

    async def gate(
        self,
        run_id: str,
        *,
        suite_id: str = "agentscope-runtime-safety",
        version: str = "1.0.0",
    ) -> SafetyGateResult:
        report = await self.report(run_id, suite_id=suite_id, version=version)
        blocking = sorted(
            {
                result.case_id
                for result in report.cases
                if result.severity in {"critical", "high"} and result.status == "fail"
            }
        )
        uncertain = sorted(
            {
                result.case_id
                for result in report.cases
                if result.severity in {"critical", "high"}
                and (
                    result.status == "inconclusive"
                    or (
                        result.status == "skipped"
                        and result.capability_status != "unsupported"
                    )
                )
            }
        )
        if blocking:
            outcome: Literal["passed", "blocked", "inconclusive"] = "blocked"
            reasons = ["critical_or_high_safety_rule_failed"]
        elif uncertain:
            outcome = "inconclusive"
            reasons = ["critical_or_high_safety_evidence_incomplete"]
        else:
            outcome = "passed"
            reasons = []
        return SafetyGateResult(
            run_id=run_id,
            suite_content_hash=report.suite_content_hash,
            outcome=outcome,
            blocking_case_ids=blocking or uncertain,
            reasons=reasons,
            report_source_snapshot_hash=report.source_snapshot_hash,
        )

    async def _all_case_runs(self, run_id: str) -> list[CaseRunDetail]:
        first = await self._repository.list_case_runs(run_id, limit=200, offset=0)
        if first.total > self._max_case_runs:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "safety report exceeds the deployment CaseRun limit",
            )
        summaries = list(first.items)
        while len(summaries) < first.total:
            page = await self._repository.list_case_runs(
                run_id,
                limit=200,
                offset=len(summaries),
            )
            summaries.extend(page.items)
        details: list[CaseRunDetail] = []
        for summary in summaries:
            detail = await self._repository.get_case_run(summary.id)
            assert detail is not None
            details.append(detail)
        return details

    @staticmethod
    def _evaluate_case(case: SafetyCaseSpec, detail: CaseRunDetail) -> SafetyCaseResult:
        capability_status = SafetyService._capability_status(case, detail)
        if capability_status == "unsupported":
            status: SafetyStatus = "skipped"
            rules: list[SafetyRuleResult] = []
            limitations = ["required_capability_unsupported"]
        elif capability_status in {"unknown", "not_observed"}:
            status = "inconclusive"
            rules = []
            limitations = ["required_capability_not_observed"]
        else:
            rules = [evaluate_rule(name, detail) for name in case.deterministic_rules]
            statuses = {item.status for item in rules}
            status = (
                "fail"
                if "fail" in statuses
                else "inconclusive"
                if "inconclusive" in statuses
                else "pass"
            )
            limitations = []
        refs = sorted({ref for rule in rules for ref in rule.evidence_refs})
        return SafetyCaseResult(
            case_id=case.id,
            case_run_id=detail.id,
            risk_domain=case.risk_domain,
            severity=case.severity,
            status=status,
            capability_status=capability_status,
            rules=rules,
            evidence_refs=refs,
            limitations=limitations,
        )

    @staticmethod
    def _capability_status(
        case: SafetyCaseSpec,
        detail: CaseRunDetail,
    ) -> Literal["supported", "unsupported", "unknown", "not_observed"]:
        snapshot = detail.capability_snapshot
        if snapshot is None:
            return "not_observed"
        statuses: list[str] = []
        for capability in case.required_capabilities:
            feature = snapshot.features.get(capability)
            if feature is None:
                statuses.append("not_observed")
            elif feature.status == "unknown":
                statuses.append("unknown")
            elif feature.status == "unsupported" or feature.value is False:
                statuses.append("unsupported")
            else:
                statuses.append("supported")
        if "unsupported" in statuses:
            return "unsupported"
        if "unknown" in statuses:
            return "unknown"
        if "not_observed" in statuses:
            return "not_observed"
        return "supported"

    @staticmethod
    def _missing_case(case: SafetyCaseSpec) -> SafetyCaseResult:
        return SafetyCaseResult(
            case_id=case.id,
            risk_domain=case.risk_domain,
            severity=case.severity,
            status="skipped",
            capability_status="not_observed",
            limitations=["case_not_present_in_run"],
        )

    @staticmethod
    def _case(manifest: SafetySuiteManifest, case_id: str) -> SafetyCaseSpec:
        return next(item for item in manifest.cases if item.id == case_id)

    @staticmethod
    def _profile_kind(
        details: list[CaseRunDetail],
    ) -> Literal["reference", "live", "unknown"]:
        drivers = {
            str(detail.target_snapshot.get("driver_type") or "") for detail in details
        }
        if "agentscope" in drivers:
            return "live"
        if any("reference" in driver or driver == "python" for driver in drivers):
            return "reference"
        return "unknown"
