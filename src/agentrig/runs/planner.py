"""将一次 run_cases 请求冻结为可执行和 skipped CaseRun。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

from ..canonical import canonical_hash
from ..capabilities import build_declared_snapshot
from ..cases import CaseService, TestCaseView
from ..errors import AgentRigError, ErrorCode
from ..evaluations.models import EvaluationOutcome, EvaluatorType
from ..identifiers import new_id
from ..profiles import ProfileService, ProfileView
from ..profiles.models import ProviderName, ToolMode
from ..profiles.resolver import ProfileResolver
from ..profiles.schemas import ExecutionProfileConfig
from ..targets import TargetService, TargetView
from ..targets.drivers import DriverCapabilities, DriverRegistry
from ..targets.options import merge_target_options
from .failure_classification import classify_failure
from .manifest import (
    ManifestEntry,
    RunManifest,
    build_run_manifest,
    manifest_cell_key,
    run_manifest_hash,
)
from .models import CaseRunStatus, RunStatus
from .repository import RunRepository
from .schemas import (
    RunCasesRequest,
    RunCellDetail,
    RunPreview,
    RunRecoveryResult,
    RunSubmitResult,
    RunTargetInput,
    RunView,
    SkippedItem,
)


@dataclass(frozen=True)
class RunPlan:
    response: RunSubmitResult
    executable_case_run_ids: list[str]
    concurrency: int


@dataclass(frozen=True)
class _Candidate:
    case: TestCaseView
    target: TargetView
    target_role: Literal["baseline", "candidate"]
    version: str | None
    repeat_index: int
    comparison_pair_id: str | None
    profile: ExecutionProfileConfig
    primary_evaluator: EvaluatorType
    driver_capabilities: DriverCapabilities | None = None


@dataclass(frozen=True)
class PreparedRun:
    """同一份请求经 V1 规则解析后的只读结果。"""

    request: RunCasesRequest
    cases: list[TestCaseView]
    targets: list[tuple[RunTargetInput, TargetView]]
    profile: ExecutionProfileConfig
    candidates: list[_Candidate]
    skipped: list[SkippedItem]
    candidate_cell_keys: list[str]
    skipped_cell_keys: list[str]
    manifest: RunManifest
    manifest_hash: str


class RunPlanner:
    def __init__(
        self,
        *,
        cases: CaseService,
        targets: TargetService,
        profiles: ProfileService,
        profile_resolver: ProfileResolver,
        drivers: DriverRegistry,
        runs: RunRepository,
        max_cases_per_run: int,
        max_planned_case_runs: int,
    ) -> None:
        self._cases = cases
        self._targets = targets
        self._profiles = profiles
        self._profile_resolver = profile_resolver
        self._drivers = drivers
        self._runs = runs
        self._max_cases_per_run = max_cases_per_run
        self._max_planned_case_runs = max_planned_case_runs

    async def plan(
        self,
        request: RunCasesRequest,
        *,
        dispatch_intent: Literal["immediate", "evaluation_plan"] = "immediate",
    ) -> RunPlan:
        prepared = await self.prepare(request)
        cases = prepared.cases
        targets = prepared.targets
        resolved_profile = prepared.profile
        valid = prepared.candidates
        skipped = prepared.skipped

        if (
            request.expected_manifest_hash is not None
            and request.expected_manifest_hash != prepared.manifest_hash
        ):
            raise AgentRigError(
                ErrorCode.PLAN_STALE,
                "run manifest no longer matches the approved preview",
                details={
                    "expected_manifest_hash": request.expected_manifest_hash,
                    "actual_manifest_hash": prepared.manifest_hash,
                },
            )

        run_id = new_id("run")
        profile_snapshot = resolved_profile.model_dump(mode="json")
        target_snapshots = [self._target_snapshot(target, item.version) for item, target in targets]
        await self._runs.create_run(
            run_id=run_id,
            selection_snapshot={
                "case_ids": request.case_ids,
                "selector": (
                    request.selector.model_dump(mode="json")
                    if request.selector is not None
                    else None
                ),
                "dispatch_intent": dispatch_intent,
            },
            resolved_case_ids=[case.id for case in cases],
            profile_snapshot=profile_snapshot,
            target_snapshots=target_snapshots,
            manifest_schema_version=prepared.manifest.manifest_schema_version,
            manifest_hash=prepared.manifest_hash,
            manifest=prepared.manifest.model_dump(mode="json"),
            cell_count=prepared.manifest.cell_count,
            attempt_count=prepared.manifest.attempt_count,
        )

        executable_ids: list[str] = []
        for candidate, cell_key in zip(
            valid,
            prepared.candidate_cell_keys,
            strict=True,
        ):
            case_run_id = new_id("case_run")
            attempt_id = new_id("eval_attempt")
            executable_ids.append(case_run_id)
            target_snapshot = self._target_snapshot(candidate.target, candidate.version)
            driver_capabilities = candidate.driver_capabilities
            assert driver_capabilities is not None
            await self._runs.create_case_run(
                case_run_id=case_run_id,
                run_id=run_id,
                case_id=candidate.case.id,
                case_snapshot=candidate.case.model_dump(mode="json"),
                target_snapshot=target_snapshot,
                profile_snapshot=candidate.profile.model_dump(mode="json"),
                capability_snapshot=build_declared_snapshot(
                    case_run_id=case_run_id,
                    target=target_snapshot,
                    profile=candidate.profile.model_dump(mode="json"),
                    driver_capabilities=driver_capabilities,
                ),
                version=candidate.version,
                repeat_index=candidate.repeat_index,
                comparison_pair_id=candidate.comparison_pair_id,
                comparison_role=candidate.target_role,
                status=CaseRunStatus.QUEUED,
                primary_evaluator=candidate.primary_evaluator,
                evaluation_state=EvaluationOutcome.AWAITING_VERDICT,
                cell_key=cell_key,
                evaluation_attempt_id=attempt_id,
                attempt_index=candidate.repeat_index,
            )
        for item, cell_key in zip(
            skipped,
            prepared.skipped_cell_keys,
            strict=True,
        ):
            matching_case = next(case for case in cases if case.id == item.case_id)
            target_input, matching_target = next(
                pair for pair in targets if pair[0].role == item.target_role
            )
            primary = self._primary_evaluator(matching_case, resolved_profile)
            skipped_case_run_id = new_id("case_run")
            attempt_id = new_id("eval_attempt")
            target_snapshot = self._target_snapshot(matching_target, item.version)
            try:
                driver_capabilities = self._drivers.capabilities(
                    matching_target.driver_type,
                    entrypoint=matching_target.options.get("entrypoint"),
                )
            except AgentRigError:
                driver_capabilities = DriverCapabilities()
            await self._runs.create_case_run(
                case_run_id=skipped_case_run_id,
                run_id=run_id,
                case_id=item.case_id,
                case_snapshot=matching_case.model_dump(mode="json"),
                target_snapshot=target_snapshot,
                profile_snapshot=profile_snapshot,
                capability_snapshot=build_declared_snapshot(
                    case_run_id=skipped_case_run_id,
                    target=target_snapshot,
                    profile=profile_snapshot,
                    driver_capabilities=driver_capabilities,
                ),
                version=item.version,
                repeat_index=item.repeat_index,
                comparison_pair_id=item.comparison_pair_id,
                comparison_role=target_input.role,
                status=CaseRunStatus.SKIPPED,
                primary_evaluator=primary,
                evaluation_state=EvaluationOutcome.INCONCLUSIVE,
                error_code=item.code,
                error_message=item.message,
                failure_class=classify_failure(
                    error_code=item.code,
                    status=CaseRunStatus.SKIPPED,
                ),
                cell_key=cell_key,
                evaluation_attempt_id=attempt_id,
                attempt_index=item.repeat_index,
            )
        await self._runs.refresh_run_counts(run_id)
        return RunPlan(
            response=RunSubmitResult(
                run_id=run_id,
                status=RunStatus.QUEUED,
                resolved_case_ids=[case.id for case in cases],
                planned_case_runs=len(executable_ids),
                manifest_hash=prepared.manifest_hash,
                cell_count=prepared.manifest.cell_count,
                attempt_count=prepared.manifest.attempt_count,
                skipped_items=skipped,
            ),
            executable_case_run_ids=executable_ids,
            concurrency=resolved_profile.concurrency,
        )

    async def recover(
        self,
        source: RunView,
        cells: list[RunCellDetail],
        *,
        reason: str,
    ) -> RunPlan:
        """Materialize a new Run exclusively from frozen source Cell snapshots."""

        profile = ExecutionProfileConfig.model_validate(source.profile_snapshot)
        selected = sorted(cells, key=lambda item: item.cell_id)
        source_attempts = [
            attempt
            for cell in selected
            for attempt in sorted(
                cell.attempt_details,
                key=lambda item: (item.attempt_index, item.id),
            )
        ]
        entries = [
            ManifestEntry(
                case_id=attempt.case_id,
                target_id=str(attempt.target_snapshot.get("id") or "unknown-target"),
                target_role=attempt.comparison_role or "candidate",
                version=attempt.version,
                repeat_index=attempt.attempt_index,
                disposition="run",
                primary_evaluator=attempt.primary_evaluator.value,
                case_snapshot=attempt.case_snapshot,
                target_snapshot=attempt.target_snapshot,
                profile_snapshot=attempt.profile_snapshot,
            )
            for attempt in source_attempts
        ]
        case_snapshots = list(
            {
                (attempt.case_id, canonical_hash(attempt.case_snapshot)): attempt.case_snapshot
                for attempt in source_attempts
            }.values()
        )
        target_snapshot_map: dict[
            tuple[str, str, str | None, str],
            tuple[str, dict[str, Any]],
        ] = {}
        for attempt in source_attempts:
            role = attempt.comparison_role or "candidate"
            snapshot = attempt.target_snapshot
            key = (
                role,
                str(snapshot.get("id") or "unknown-target"),
                attempt.version,
                canonical_hash(snapshot),
            )
            target_snapshot_map[key] = (role, snapshot)
        manifest = build_run_manifest(
            selection={
                "recovery_of_run_id": source.id,
                "selected_cell_ids": [item.cell_id for item in selected],
                "reason": reason,
            },
            case_snapshots=case_snapshots,
            target_snapshots=list(target_snapshot_map.values()),
            profile_id=(
                source.manifest.profile.id
                if source.manifest is not None
                else "recovery-source-profile"
            ),
            profile_snapshot=source.profile_snapshot,
            repeat_count=max(item.attempt_index for item in source_attempts),
            entries=entries,
        )
        manifest_hash = run_manifest_hash(manifest)
        run_id = new_id("run")
        await self._runs.create_run(
            run_id=run_id,
            selection_snapshot=manifest.selection,
            resolved_case_ids=list(dict.fromkeys(item.case_id for item in source_attempts)),
            profile_snapshot=source.profile_snapshot,
            target_snapshots=[item[1] for item in target_snapshot_map.values()],
            manifest_schema_version=manifest.manifest_schema_version,
            manifest_hash=manifest_hash,
            manifest=manifest.model_dump(mode="json"),
            recovery_of_run_id=source.id,
            recovery_reason=reason,
            cell_count=manifest.cell_count,
            attempt_count=manifest.attempt_count,
        )

        executable_ids: list[str] = []
        for attempt, entry in zip(source_attempts, entries, strict=True):
            case_run_id = new_id("case_run")
            executable_ids.append(case_run_id)
            try:
                capabilities = self._drivers.capabilities(
                    str(attempt.target_snapshot.get("driver_type") or ""),
                    entrypoint=dict(attempt.target_snapshot.get("options") or {}).get(
                        "entrypoint"
                    ),
                )
            except AgentRigError:
                capabilities = DriverCapabilities()
            await self._runs.create_case_run(
                case_run_id=case_run_id,
                run_id=run_id,
                case_id=attempt.case_id,
                case_snapshot=attempt.case_snapshot,
                target_snapshot=attempt.target_snapshot,
                profile_snapshot=attempt.profile_snapshot,
                capability_snapshot=build_declared_snapshot(
                    case_run_id=case_run_id,
                    target=attempt.target_snapshot,
                    profile=attempt.profile_snapshot,
                    driver_capabilities=capabilities,
                ),
                version=attempt.version,
                repeat_index=attempt.repeat_index,
                comparison_pair_id=attempt.comparison_pair_id,
                comparison_role=attempt.comparison_role,
                status=CaseRunStatus.QUEUED,
                primary_evaluator=attempt.primary_evaluator,
                evaluation_state=EvaluationOutcome.AWAITING_VERDICT,
                cell_key=manifest_cell_key(entry),
                evaluation_attempt_id=new_id("eval_attempt"),
                attempt_index=attempt.attempt_index,
                recovery_of_case_run_id=attempt.id,
            )
        await self._runs.refresh_run_counts(run_id)
        return RunPlan(
            response=RunRecoveryResult(
                run_id=run_id,
                status=RunStatus.QUEUED,
                resolved_case_ids=list(
                    dict.fromkeys(item.case_id for item in source_attempts)
                ),
                planned_case_runs=len(executable_ids),
                manifest_hash=manifest_hash,
                cell_count=manifest.cell_count,
                attempt_count=manifest.attempt_count,
                recovery_of_run_id=source.id,
                recovery_reason=reason,
                selected_cell_ids=[item.cell_id for item in selected],
            ),
            executable_case_run_ids=executable_ids,
            concurrency=profile.concurrency,
        )

    async def prepare(self, request: RunCasesRequest) -> PreparedRun:
        """复用正式运行的全部解析和预检规则，但不创建任何数据库事实。"""

        cases = await self._resolve_cases(request)
        targets = [(item, await self._resolve_target(item)) for item in request.targets]
        profile = await self._resolve_profile(request.profile_id)
        resolved_profile = self._profile_resolver.resolve(
            profile,
            request.overrides.model_dump(mode="json", exclude_none=True),
            repeat_count=request.repeat_count,
        )
        candidates, skipped = self._expand(cases, targets, resolved_profile)
        valid: list[_Candidate] = []
        for candidate in candidates:
            try:
                driver_capabilities = self._drivers.capabilities(
                    candidate.target.driver_type,
                    entrypoint=candidate.target.options.get("entrypoint"),
                )
            except AgentRigError as exc:
                skipped.append(self._skip(candidate, exc.detail.code.value, exc.detail.message))
                continue
            reason = self._preflight(candidate, driver_capabilities)
            if reason is None:
                valid.append(replace(candidate, driver_capabilities=driver_capabilities))
            else:
                skipped.append(reason)
        if not valid:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "run request has no executable case runs",
                details={
                    "resolved_case_ids": [case.id for case in cases],
                    "skipped_items": [item.model_dump(mode="json") for item in skipped],
                },
            )
        profile_snapshot = resolved_profile.model_dump(mode="json")
        case_snapshots = [case.model_dump(mode="json") for case in cases]
        target_snapshots = [
            (item.role, self._target_snapshot(target, item.version))
            for item, target in targets
        ]
        candidate_entries = [
            ManifestEntry(
                case_id=candidate.case.id,
                target_id=candidate.target.id,
                target_role=candidate.target_role,
                version=candidate.version,
                repeat_index=candidate.repeat_index,
                disposition="run",
                primary_evaluator=candidate.primary_evaluator.value,
                case_snapshot=candidate.case.model_dump(mode="json"),
                target_snapshot=self._target_snapshot(candidate.target, candidate.version),
                profile_snapshot=candidate.profile.model_dump(mode="json"),
            )
            for candidate in valid
        ]
        skipped_entries: list[ManifestEntry] = []
        for item in skipped:
            matching_case = next(case for case in cases if case.id == item.case_id)
            _target_input, matching_target = next(
                pair for pair in targets if pair[0].role == item.target_role
            )
            skipped_entries.append(
                ManifestEntry(
                    case_id=item.case_id,
                    target_id=matching_target.id,
                    target_role=item.target_role,
                    version=item.version,
                    repeat_index=item.repeat_index,
                    disposition="skip",
                    primary_evaluator=self._primary_evaluator(
                        matching_case,
                        resolved_profile,
                    ).value,
                    case_snapshot=matching_case.model_dump(mode="json"),
                    target_snapshot=self._target_snapshot(matching_target, item.version),
                    profile_snapshot=profile_snapshot,
                    code=item.code,
                    message=item.message,
                )
            )
        manifest = build_run_manifest(
            selection=request.model_dump(
                mode="json",
                exclude={"expected_manifest_hash"},
            ),
            case_snapshots=case_snapshots,
            target_snapshots=target_snapshots,
            profile_id=request.profile_id or "deployment-default",
            profile_snapshot=profile_snapshot,
            repeat_count=resolved_profile.repeat_count,
            entries=[*candidate_entries, *skipped_entries],
        )
        return PreparedRun(
            request=request,
            cases=cases,
            targets=targets,
            profile=resolved_profile,
            candidates=valid,
            skipped=skipped,
            candidate_cell_keys=[manifest_cell_key(item) for item in candidate_entries],
            skipped_cell_keys=[manifest_cell_key(item) for item in skipped_entries],
            manifest=manifest,
            manifest_hash=run_manifest_hash(manifest),
        )

    async def preview(self, request: RunCasesRequest) -> RunPreview:
        prepared = await self.prepare(request)
        return RunPreview(
            resolved_case_ids=[case.id for case in prepared.cases],
            planned_case_runs=len(prepared.candidates),
            skipped_items=prepared.skipped,
            profile_snapshot=prepared.profile.model_dump(mode="json"),
            target_snapshots=[
                self._target_snapshot(target, item.version) for item, target in prepared.targets
            ],
            primary_evaluators=sorted(
                {item.primary_evaluator for item in prepared.candidates},
                key=lambda item: item.value,
            ),
            providers=[item.name.value for item in prepared.profile.provider_chain],
            manifest_schema_version=prepared.manifest.manifest_schema_version,
            manifest_hash=prepared.manifest_hash,
            manifest=prepared.manifest,
            cell_count=prepared.manifest.cell_count,
            attempt_count=prepared.manifest.attempt_count,
        )

    async def _resolve_cases(self, request: RunCasesRequest) -> list[TestCaseView]:
        if request.case_ids:
            self._ensure_case_count(len(request.case_ids))
            return [await self._cases.get(case_id) for case_id in request.case_ids]
        assert request.selector is not None
        items: list[TestCaseView] = []
        offset = 0
        while True:
            page = await self._cases.list_cases(
                request.selector,
                limit=200,
                offset=offset,
            )
            self._ensure_case_count(page.total)
            items.extend(page.items)
            offset += len(page.items)
            if offset >= page.total:
                break
        if not items:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                "selector did not match any test cases",
                details={"selector": request.selector.model_dump(mode="json")},
            )
        return items

    def _ensure_case_count(self, count: int) -> None:
        if count > self._max_cases_per_run:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "run selection exceeds the deployment case limit",
                details={
                    "selected_case_count": count,
                    "max_cases_per_run": self._max_cases_per_run,
                },
            )

    async def _resolve_target(self, value: RunTargetInput) -> TargetView:
        if value.target_id is not None:
            target = await self._targets.get(value.target_id)
        else:
            assert value.inline_target is not None
            now = datetime.now(timezone.utc)
            inline_hash = canonical_hash(
                value.inline_target.model_dump(mode="json", exclude={"id"})
            ).removeprefix("sha256:")
            target = TargetView.model_validate(
                {
                    **value.inline_target.model_dump(mode="json"),
                    "id": value.inline_target.id or f"inline_target_{inline_hash[:24]}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        await self._targets.authorize_execution(target, version=value.version)
        return target

    async def _resolve_profile(self, profile_id: str | None) -> ProfileView | None:
        return await self._profiles.get(profile_id) if profile_id else None

    def _expand(
        self,
        cases: list[TestCaseView],
        targets: list[tuple[RunTargetInput, TargetView]],
        profile: ExecutionProfileConfig,
    ) -> tuple[list[_Candidate], list[SkippedItem]]:
        candidates: list[_Candidate] = []
        skipped: list[SkippedItem] = []
        pair_ids: dict[tuple[str, int, str | None], str] = {}
        both_explicit = len(targets) == 2 and all(item.version is not None for item, _ in targets)
        for case in cases:
            for repeat_index in range(1, profile.repeat_count + 1):
                for target_input, target in targets:
                    versions, incompatible = self._versions(case, target, target_input.version)
                    for version, message in incompatible:
                        pair_key_version = None if both_explicit else version
                        pair_id = (
                            pair_ids.setdefault(
                                (case.id, repeat_index, pair_key_version),
                                self._comparison_pair_id(
                                    case.id,
                                    repeat_index,
                                    pair_key_version,
                                ),
                            )
                            if len(targets) == 2
                            else None
                        )
                        skipped.append(
                            SkippedItem(
                                case_id=case.id,
                                target_role=target_input.role,
                                version=version,
                                repeat_index=repeat_index,
                                comparison_pair_id=pair_id,
                                code=ErrorCode.VERSION_INCOMPATIBLE.value,
                                message=message,
                            )
                        )
                        self._ensure_case_run_count(len(candidates) + len(skipped))
                    for version in versions:
                        pair_key_version = None if both_explicit else version
                        pair_id = (
                            pair_ids.setdefault(
                                (case.id, repeat_index, pair_key_version),
                                self._comparison_pair_id(
                                    case.id,
                                    repeat_index,
                                    pair_key_version,
                                ),
                            )
                            if len(targets) == 2
                            else None
                        )
                        candidates.append(
                            _Candidate(
                                case=case,
                                target=target,
                                target_role=target_input.role,
                                version=version,
                                repeat_index=repeat_index,
                                comparison_pair_id=pair_id,
                                profile=profile,
                                primary_evaluator=self._primary_evaluator(case, profile),
                            )
                        )
                        self._ensure_case_run_count(len(candidates) + len(skipped))
        return candidates, skipped

    @staticmethod
    def _comparison_pair_id(
        case_id: str,
        repeat_index: int,
        version: str | None,
    ) -> str:
        digest = canonical_hash(
            {
                "case_id": case_id,
                "repeat_index": repeat_index,
                "version": version,
            }
        ).removeprefix("sha256:")
        return f"pair_{digest[:32]}"

    def _ensure_case_run_count(self, count: int) -> None:
        if count > self._max_planned_case_runs:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "run expansion exceeds the deployment CaseRun limit",
                details={
                    "expanded_case_run_count": count,
                    "max_planned_case_runs": self._max_planned_case_runs,
                },
            )

    @staticmethod
    def _versions(
        case: TestCaseView,
        target: TargetView,
        requested: str | None,
    ) -> tuple[list[str | None], list[tuple[str | None, str]]]:
        supported = case.supported_versions
        registered = [item.version for item in target.versions]
        accepts_all = not supported or "*" in supported
        if requested is not None:
            if not accepts_all and requested not in supported:
                return [], [
                    (
                        requested,
                        f"case {case.id} does not support version {requested}",
                    )
                ]
            return [requested], []
        if not accepts_all:
            versions: list[str | None] = list(dict.fromkeys(supported))
            incompatible: list[tuple[str | None, str]] = [
                (
                    version,
                    f"case {case.id} does not support version {version}",
                )
                for version in registered
                if version not in supported
            ]
            return versions, incompatible
        if registered:
            return list(registered), []
        return [None], []

    def _preflight(
        self,
        candidate: _Candidate,
        capabilities: DriverCapabilities,
    ) -> SkippedItem | None:
        missing = self._missing_capability(candidate, capabilities)
        if missing:
            return self._skip(
                candidate,
                ErrorCode.DRIVER_CAPABILITY_MISSING.value,
                f"driver is missing required capability: {missing}",
            )
        assertions = candidate.case.case_assertions or [
            assertion for turn in candidate.case.turns for assertion in turn.assertions
        ]
        rubrics = [
            candidate.case.case_rubric,
            *(turn.rubric for turn in candidate.case.turns),
        ]
        if candidate.primary_evaluator is EvaluatorType.RULE and not assertions:
            return self._skip(
                candidate,
                ErrorCode.INVALID_EVALUATION_CONFIG.value,
                "rule evaluator requires at least one assertion",
            )
        if candidate.primary_evaluator is EvaluatorType.EVIDENCE_JUDGE and not any(rubrics):
            return self._skip(
                candidate,
                ErrorCode.INVALID_EVALUATION_CONFIG.value,
                "evidence_judge requires a case or turn rubric",
            )
        return None

    @staticmethod
    def _missing_capability(
        candidate: _Candidate,
        capabilities: DriverCapabilities,
    ) -> str | None:
        if len(candidate.case.turns) > 1 and not capabilities.multi_turn:
            return "multi_turn"
        if candidate.profile.tool_mode is ToolMode.CONTROLLED:
            if not capabilities.tool_call_observation:
                return "tool_call_observation"
            if not capabilities.tool_result_injection:
                return "tool_result_injection"
        if candidate.profile.tool_mode is ToolMode.PROXY and not capabilities.tool_proxy_injection:
            return "tool_proxy_injection"
        if candidate.profile.tool_mode is ToolMode.OBSERVE_ONLY:
            has_fixture = any(turn.fixtures for turn in candidate.case.turns)
            chain = {item.name for item in candidate.profile.provider_chain}
            if has_fixture or ProviderName.SIMULATION_CURATOR in chain:
                return "tool_result_injection"
        return None

    @staticmethod
    def _primary_evaluator(
        case: TestCaseView,
        profile: ExecutionProfileConfig,
    ) -> EvaluatorType:
        value = profile.primary_evaluator or case.primary_evaluator
        return EvaluatorType(value)

    @staticmethod
    def _target_snapshot(target: TargetView, version: str | None) -> dict[str, Any]:
        version_config = next(
            (item for item in target.versions if item.version == version),
            None,
        )
        return {
            "id": target.id,
            "name": target.name,
            "driver_type": target.driver_type,
            "endpoint": (
                version_config.endpoint
                if version_config is not None and version_config.endpoint is not None
                else target.endpoint
            ),
            "secret_ref": target.secret_ref,
            "options": merge_target_options(
                target.options,
                version_config.options if version_config is not None else {},
            ),
            "version": version,
        }

    @staticmethod
    def _skip(candidate: _Candidate, code: str, message: str) -> SkippedItem:
        return SkippedItem(
            case_id=candidate.case.id,
            target_role=candidate.target_role,
            version=candidate.version,
            repeat_index=candidate.repeat_index,
            comparison_pair_id=candidate.comparison_pair_id,
            code=code,
            message=message,
        )
