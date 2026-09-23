"""在进程内执行一次本地测试运行，把结果整理成按用例的结论。"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from ..agents.model_client import ModelClient
from ..bootstrap import ServiceContainer
from ..config import DatabaseConfig, ExecutionConfig, Settings
from ..evaluations.models import EvaluationOutcome
from ..profiles import ProfileCreate
from ..profiles.schemas import ExecutionProfileConfig
from ..runs.models import RunEventType
from ..runs.schemas import CaseRunDetail, RunCasesRequest, RunTargetInput, SkippedItem
from ..targets import TargetCreate
from ..targets.schemas import TargetVersion
from .loader import LoadedCase, LoadedProject, display
from .schemas import ProjectModel

Status = Literal["passed", "failed", "inconclusive"]
PROFILE_ID = "profile_local_test"
_PAGE_SIZE = 50


class TargetUnavailableError(RuntimeError):
    """被测 Agent 无法启动或握手失败，属于配置错误。"""


@dataclass(frozen=True)
class ResolvedTarget:
    target_id: str
    name: str
    version: str
    python: str
    secret_ref: str | None
    options: dict[str, Any]


@dataclass(frozen=True)
class FailedCriterion:
    criterion: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class AttemptResult:
    status: Status
    failures: tuple[FailedCriterion, ...] = ()
    error: str | None = None
    duration_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    name: str
    path: str
    turns: int
    attempts: tuple[AttemptResult, ...]

    @property
    def status(self) -> Status:
        statuses = {attempt.status for attempt in self.attempts}
        if "failed" in statuses:
            return "failed"
        return "passed" if statuses == {"passed"} else "inconclusive"

    @property
    def duration_seconds(self) -> float | None:
        durations = [item.duration_seconds for item in self.attempts if item.duration_seconds]
        return max(durations) if durations else None


@dataclass(frozen=True)
class TestReport:
    __test__: ClassVar[bool] = False

    target: str
    version: str
    run_id: str
    concurrency: int
    repeat: int
    elapsed_seconds: float
    outcomes: tuple[CaseOutcome, ...]

    def count(self, status: Status) -> int:
        return sum(outcome.status == status for outcome in self.outcomes)

    @property
    def input_tokens(self) -> int:
        return sum(a.input_tokens for outcome in self.outcomes for a in outcome.attempts)

    @property
    def output_tokens(self) -> int:
        return sum(a.output_tokens for outcome in self.outcomes for a in outcome.attempts)

    @property
    def exit_code(self) -> int:
        """与 ``agentrig gate`` 一致：2 出现回归，3 无法判定，0 全部通过。"""

        if self.count("failed"):
            return 2
        if self.count("inconclusive") or not self.outcomes:
            return 3
        return 0


def resolve_target(project: LoadedProject) -> ResolvedTarget:
    """把项目文件里的相对路径换成绝对路径，生成 python_agent Target 配置。"""

    target = project.config.target
    python = _absolute(project, target.python) if target.python else sys.executable
    location, _, attribute = target.entry.rpartition(":")
    entry = (
        f"{_absolute(project, location)}:{attribute}"
        if location.endswith(".py")
        else target.entry
    )
    options: dict[str, Any] = {
        "entry": entry,
        "python": python,
        "cwd": _absolute(project, target.cwd),
        "adapter": target.adapter,
        "factory": target.factory,
        "env": dict(target.env),
        "inherit_env": list(target.inherit_env),
        "startup_timeout_seconds": target.startup_timeout_seconds,
        "conversation_initial_state": project.config.initial_state,
    }
    if target.credential_env is not None:
        options["credential_env"] = target.credential_env
    return ResolvedTarget(
        target_id=f"target_{target.name}",
        name=target.name,
        version=target.version,
        python=python,
        secret_ref=target.secret,
        options=options,
    )


def effective_providers(project: LoadedProject, *, no_curator: bool) -> list[str]:
    providers: list[str] = list(project.config.profile.providers)
    if no_curator:
        providers = [name for name in providers if name != "simulation_curator"]
    return providers


def preflight_problems(
    project: LoadedProject,
    cases: list[LoadedCase],
    providers: list[str],
) -> list[str]:
    """启动前就能发现的配置问题：缺少模型、缺少 Key、本地无法给出结论的评判方式。"""

    profile = project.config.profile
    problems: list[str] = []
    if not providers:
        problems.append("没有可用的工具结果来源：profile.providers 为空")
    if "simulation_curator" in providers:
        if profile.curator is None:
            problems.append(
                "profile.providers 包含 simulation_curator，但没有配置 profile.curator；"
                "请配置 Curator 模型，或加 --no-curator"
            )
        elif _missing_env(profile.curator.secret):
            problems.append(
                f"Curator 的模型 Key 未设置：环境变量 {_env_name(profile.curator.secret)}；"
                "请设置后重试，或加 --no-curator"
            )
    judged = [item.case_id for item in cases if item.case.primary_evaluator == "evidence_judge"]
    if judged:
        if profile.judge is None:
            problems.append(f"用例 {', '.join(judged[:3])} 使用 evidence_judge，需要配置 profile.judge")
        elif _missing_env(profile.judge.secret):
            problems.append(
                f"Judge 的模型 Key 未设置：环境变量 {_env_name(profile.judge.secret)}"
            )
    external = [
        item.case_id for item in cases if item.case.primary_evaluator == "external_controller"
    ]
    if external:
        problems.append(
            f"用例 {', '.join(external[:3])} 使用 external_controller，需要外部控制方提交结论，"
            "本地测试无法判定"
        )
    secret = project.config.target.secret
    if secret is not None and _missing_env(secret):
        problems.append(f"被测 Agent 的 Key 未设置：环境变量 {_env_name(secret)}")
    return problems


async def execute(
    cases: list[LoadedCase],
    *,
    project: LoadedProject,
    target: ResolvedTarget,
    providers: list[str],
    database_url: str,
    concurrency: int,
    repeat: int,
    model_client: ModelClient | None = None,
) -> TestReport:
    """写入 Target、执行配置与用例，提交一次运行并等待完成。"""

    started = time.monotonic()
    settings = Settings(
        database=DatabaseConfig(url=database_url),
        execution=ExecutionConfig(
            # 本地命令本来就会执行仓库里的代码；放行名单只对这次进程内运行生效。
            subprocess_allowlist=[target.python],
            default_concurrency=concurrency,
            max_concurrency=max(20, concurrency),
            max_repeat_count=max(20, repeat),
            max_cases_per_run=max(200, len(cases)),
            max_planned_case_runs=max(1_000, len(cases) * repeat),
        ),
    )
    container = ServiceContainer.build(settings, model_client=model_client)
    await container.initialize()
    try:
        await container.targets.create(
            TargetCreate(
                id=target.target_id,
                name=target.name,
                driver_type="python_agent",
                secret_ref=target.secret_ref,
                options=target.options,
                versions=[TargetVersion(version=target.version)],
            )
        )
        check = await container.targets.check(target.target_id, version=target.version)
        if not check.reachable:
            raise TargetUnavailableError(check.message)
        await container.profiles.create(
            ProfileCreate(
                id=PROFILE_ID,
                name="agentrig test",
                config=ExecutionProfileConfig.model_validate(
                    _profile_config(project, providers, concurrency, repeat)
                ),
            )
        )
        for item in cases:
            await container.cases.create(item.case)
        submitted = await container.runs.run_cases(
            RunCasesRequest(
                case_ids=[item.case_id for item in cases],
                targets=[RunTargetInput(target_id=target.target_id, version=target.version)],
                profile_id=PROFILE_ID,
            )
        )
        await container.scheduler.wait(submitted.run_id)
        details = await _case_runs(container, submitted.run_id)
    finally:
        await container.close()
    return TestReport(
        target=target.name,
        version=target.version,
        run_id=submitted.run_id,
        concurrency=concurrency,
        repeat=repeat,
        elapsed_seconds=time.monotonic() - started,
        outcomes=_outcomes(cases, details, submitted.skipped_items),
    )


def _profile_config(
    project: LoadedProject,
    providers: list[str],
    concurrency: int,
    repeat: int,
) -> dict[str, Any]:
    profile = project.config.profile
    config: dict[str, Any] = {
        "tool_mode": "controlled",
        "provider_chain": [{"name": name} for name in providers],
        "concurrency": concurrency,
        "repeat_count": repeat,
        "case_timeout_seconds": profile.case_timeout_seconds,
    }
    if "simulation_curator" in providers and profile.curator is not None:
        config["curator_model"] = _model_ref(profile.curator)
    if profile.judge is not None:
        config["judge_model"] = _model_ref(profile.judge)
    return config


async def _case_runs(container: ServiceContainer, run_id: str) -> list[CaseRunDetail]:
    details: list[CaseRunDetail] = []
    offset = 0
    while True:
        page = await container.runs.list_case_runs(run_id, limit=_PAGE_SIZE, offset=offset)
        for item in page.items:
            details.append(await container.runs.get_case_run(item.id))
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return details


def _outcomes(
    cases: list[LoadedCase],
    details: list[CaseRunDetail],
    skipped: list[SkippedItem],
) -> tuple[CaseOutcome, ...]:
    by_case: dict[str, list[CaseRunDetail]] = defaultdict(list)
    for detail in details:
        by_case[detail.case_id].append(detail)
    reasons = {item.case_id: f"{item.code}: {item.message}" for item in skipped}
    outcomes: list[CaseOutcome] = []
    for item in cases:
        runs = sorted(by_case.get(item.case_id, []), key=lambda detail: detail.repeat_index)
        attempts = tuple(_attempt(detail) for detail in runs) or (
            AttemptResult(
                status="inconclusive",
                error=reasons.get(item.case_id, "用例没有被执行"),
            ),
        )
        outcomes.append(
            CaseOutcome(
                case_id=item.case_id,
                name=item.case.name,
                path=display(item.path),
                turns=len(item.case.turns),
                attempts=attempts,
            )
        )
    return tuple(outcomes)


def _attempt(detail: CaseRunDetail) -> AttemptResult:
    events = {event.id: event for event in detail.events}
    sources = {
        str(event.payload.get("tool_call_id")): str(event.payload.get("source"))
        for event in detail.events
        if event.event_type is RunEventType.TOOL_RESULT
    }
    usage = [event.payload for event in detail.events if event.event_type is RunEventType.USAGE]
    status: Status = (
        "passed"
        if detail.evaluation_state is EvaluationOutcome.PASS
        else "failed"
        if detail.evaluation_state is EvaluationOutcome.FAIL
        else "inconclusive"
    )
    failures: list[FailedCriterion] = []
    for evaluation in detail.evaluations:
        if evaluation.verdict != "fail":
            continue
        criteria = [item for item in evaluation.criteria if item.verdict == "fail"]
        if not criteria:
            failures.append(FailedCriterion(criterion=evaluation.summary))
        for criterion in criteria:
            failures.append(
                FailedCriterion(
                    criterion=criterion.criterion,
                    evidence=tuple(
                        _evidence(events[ref].event_type, events[ref].payload, sources)
                        for ref in criterion.evidence_refs
                        if ref in events
                    ),
                )
            )
    error: str | None = None
    if status == "inconclusive":
        if detail.error_code:
            error = f"{detail.error_code}: {detail.error_message or ''}".rstrip(": ")
        else:
            error = next(
                (item.summary for item in detail.evaluations if item.verdict != "pass"),
                detail.evaluation_state.value,
            )
        unresolved = [
            event.payload
            for event in detail.events
            if event.event_type is RunEventType.TOOL_CALL
            and not event.payload.get("observed_only")
            and str(event.payload.get("tool_call_id")) not in sources
        ]
        if unresolved:
            # 指出具体是哪一次工具调用没有拿到结果，方便补 Fixture。
            call = unresolved[-1]
            error = (
                f"{error}；第 {call.get('turn_position')} 轮调用 {call.get('tool_name')} "
                "没有可用的结果"
            )
    duration = (
        (detail.finished_at - detail.started_at).total_seconds()
        if detail.started_at is not None and detail.finished_at is not None
        else None
    )
    return AttemptResult(
        status=status,
        failures=tuple(failures),
        error=error,
        duration_seconds=duration,
        input_tokens=sum(_int(item.get("input_tokens")) for item in usage),
        output_tokens=sum(_int(item.get("output_tokens")) for item in usage),
    )


def _evidence(
    event_type: RunEventType,
    payload: dict[str, Any],
    sources: dict[str, str],
) -> str:
    if event_type is RunEventType.TOOL_CALL:
        arguments = json.dumps(payload.get("arguments") or {}, ensure_ascii=False)
        text = (
            f"第 {payload.get('turn_position')} 轮调用 {payload.get('tool_name')} "
            f"{_clip(arguments)}"
        )
        source = sources.get(str(payload.get("tool_call_id")))
        return f"{text}，结果来自 {source}" if source else text
    content = payload.get("text")
    if isinstance(content, str) and content:
        return f"{event_type.value}: {_clip(content)}"
    return event_type.value


def _model_ref(model: ProjectModel) -> dict[str, Any]:
    return {
        "base_url": model.base_url,
        "model": model.model,
        "secret_ref": model.secret,
        "options": model.options,
    }


def _absolute(project: LoadedProject, value: str) -> str:
    # 不解析符号链接：虚拟环境里的 python 通常是软链，解析后会丢掉 venv。
    path = Path(value)
    return os.path.abspath(path if path.is_absolute() else project.root / path)


def _env_name(secret_ref: str) -> str:
    return secret_ref.removeprefix("env:")


def _missing_env(secret_ref: str) -> bool:
    return not os.environ.get(_env_name(secret_ref))


def _int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _clip(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
