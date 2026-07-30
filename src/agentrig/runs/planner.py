"""将一次 run_cases 请求冻结为可执行和 skipped CaseRun。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

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
from .models import CaseRunStatus, RunStatus
from .repository import RunRepository
from .schemas import (
    RunCasesRequest,
    RunSubmitResult,
    RunTargetInput,
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
    ) -> None:
        self._cases = cases
        self._targets = targets
        self._profiles = profiles
        self._profile_resolver = profile_resolver
        self._drivers = drivers
        self._runs = runs

    async def plan(self, request: RunCasesRequest) -> RunPlan:
        cases = await self._resolve_cases(request)
        targets = [
            (item, await self._resolve_target(item))
            for item in request.targets
        ]
        profile = await self._resolve_profile(request.profile_id)
        resolved_profile = self._profile_resolver.resolve(
            profile,
            request.overrides.model_dump(mode="json", exclude_none=True),
            repeat_count=request.repeat_count,
        )
        candidates, skipped = self._expand(cases, targets, resolved_profile)
        valid: list[_Candidate] = []
        for candidate in candidates:
            reason = self._preflight(candidate)
            if reason is None:
                valid.append(candidate)
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

        run_id = new_id("run")
        profile_snapshot = resolved_profile.model_dump(mode="json")
        target_snapshots = [
            self._target_snapshot(target, item.version)
            for item, target in targets
        ]
        await self._runs.create_run(
            run_id=run_id,
            selection_snapshot={
                "case_ids": request.case_ids,
                "selector": (
                    request.selector.model_dump(mode="json")
                    if request.selector is not None
                    else None
                ),
            },
            resolved_case_ids=[case.id for case in cases],
            profile_snapshot=profile_snapshot,
            target_snapshots=target_snapshots,
        )

        executable_ids: list[str] = []
        for candidate in valid:
            case_run_id = new_id("case_run")
            executable_ids.append(case_run_id)
            await self._runs.create_case_run(
                case_run_id=case_run_id,
                run_id=run_id,
                case_id=candidate.case.id,
                case_snapshot=candidate.case.model_dump(mode="json"),
                target_snapshot=self._target_snapshot(candidate.target, candidate.version),
                profile_snapshot=candidate.profile.model_dump(mode="json"),
                version=candidate.version,
                repeat_index=candidate.repeat_index,
                comparison_pair_id=candidate.comparison_pair_id,
                comparison_role=candidate.target_role,
                status=CaseRunStatus.QUEUED,
                primary_evaluator=candidate.primary_evaluator,
                evaluation_state=EvaluationOutcome.AWAITING_VERDICT,
            )
        for item in skipped:
            matching_case = next(case for case in cases if case.id == item.case_id)
            target_input, matching_target = next(
                pair for pair in targets if pair[0].role == item.target_role
            )
            primary = self._primary_evaluator(matching_case, resolved_profile)
            await self._runs.create_case_run(
                case_run_id=new_id("case_run"),
                run_id=run_id,
                case_id=item.case_id,
                case_snapshot=matching_case.model_dump(mode="json"),
                target_snapshot=self._target_snapshot(matching_target, item.version),
                profile_snapshot=profile_snapshot,
                version=item.version,
                repeat_index=item.repeat_index,
                comparison_pair_id=item.comparison_pair_id,
                comparison_role=target_input.role,
                status=CaseRunStatus.SKIPPED,
                primary_evaluator=primary,
                evaluation_state=EvaluationOutcome.INCONCLUSIVE,
                error_code=item.code,
                error_message=item.message,
            )
        await self._runs.refresh_run_counts(run_id)
        return RunPlan(
            response=RunSubmitResult(
                run_id=run_id,
                status=RunStatus.QUEUED,
                resolved_case_ids=[case.id for case in cases],
                planned_case_runs=len(executable_ids),
                skipped_items=skipped,
            ),
            executable_case_run_ids=executable_ids,
            concurrency=resolved_profile.concurrency,
        )

    async def _resolve_cases(self, request: RunCasesRequest) -> list[TestCaseView]:
        if request.case_ids:
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

    async def _resolve_target(self, value: RunTargetInput) -> TargetView:
        if value.target_id is not None:
            return await self._targets.get(value.target_id)
        assert value.inline_target is not None
        now = datetime.now(timezone.utc)
        return TargetView.model_validate(
            {
                **value.inline_target.model_dump(mode="json"),
                "id": value.inline_target.id or new_id("inline_target"),
                "created_at": now,
                "updated_at": now,
            }
        )

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
                                new_id("pair"),
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
                    for version in versions:
                        pair_key_version = None if both_explicit else version
                        pair_id = (
                            pair_ids.setdefault(
                                (case.id, repeat_index, pair_key_version),
                                new_id("pair"),
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
        return candidates, skipped

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

    def _preflight(self, candidate: _Candidate) -> SkippedItem | None:
        try:
            capabilities = self._drivers.capabilities(
                candidate.target.driver_type,
                entrypoint=candidate.target.options.get("entrypoint"),
            )
        except AgentRigError as exc:
            return self._skip(candidate, exc.detail.code.value, exc.detail.message)
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
        if (
            candidate.profile.tool_mode is ToolMode.PROXY
            and not capabilities.tool_proxy_injection
        ):
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
