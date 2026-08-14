"""AgentRig CLI 入口。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from .config import get_settings
from .errors import AgentRigError
from .gates import ReleaseGateResult, ReleasePolicy
from .infrastructure.database.migrations import migration_config


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.cmd == "serve":
        settings = get_settings()
        host: str = args.host if args.host is not None else settings.server.host
        port: int = args.port if args.port is not None else settings.server.port
        uvicorn.run("agentrig.app:app", host=host, port=port, reload=args.reload)
    elif args.cmd == "demo":
        from .demo import run_demo

        raise SystemExit(asyncio.run(run_demo()))
    elif args.cmd == "db":
        from alembic import command

        with migration_config() as config:
            if args.action == "upgrade":
                command.upgrade(config, "head")
            elif args.action == "downgrade":
                command.downgrade(config, "-1")
            else:
                command.current(config, verbose=True)
    elif args.cmd == "report":
        raise SystemExit(asyncio.run(_run_report_command(args)))
    elif args.cmd == "gate":
        raise SystemExit(asyncio.run(_run_gate_command(args)))
    elif args.cmd == "safety":
        raise SystemExit(asyncio.run(_run_safety_command(args)))
    elif args.cmd == "agentteams-compat":
        raise SystemExit(_run_agentteams_compat_command(args))
    elif args.cmd == "worker":
        raise SystemExit(asyncio.run(_run_worker_command(args)))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentrig", description="AgentRig 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="启动 AgentRig 服务")
    serve.add_argument("--reload", action="store_true", help="启用热重载")
    serve.add_argument("--host", default=None, help="覆盖监听 host")
    serve.add_argument("--port", type=int, default=None, help="覆盖监听端口")

    sub.add_parser("demo", help="一键验收 V1 异步执行、Fixture 和 Rule 闭环")
    database = sub.add_parser("db", help="管理 AgentRig 数据库迁移")
    database.add_argument(
        "action",
        choices=["upgrade", "downgrade", "current"],
        help="upgrade 到最新、downgrade 一个版本或查看当前版本",
    )

    report = sub.add_parser("report", help="生成终态 Run 的质量或 A/B 对比报告")
    report_sub = report.add_subparsers(dest="report_kind", required=True)
    for kind in ("quality", "comparison"):
        command = report_sub.add_parser(kind, help=f"生成 {kind} 报告")
        command.add_argument("--run-id", required=True)
        command.add_argument(
            "--format",
            choices=["json", "markdown"],
            default="json",
        )
        command.add_argument("--output", default="-", help="输出路径；- 表示 stdout")

    gate = sub.add_parser("gate", help="执行版本化发布门禁")
    gate_sub = gate.add_subparsers(dest="gate_action", required=True)
    evaluate = gate_sub.add_parser("evaluate", help="对 A/B Run 执行发布门禁")
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--policy", required=True, help="ReleasePolicy JSON 文件")
    evaluate.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
    )
    evaluate.add_argument("--output", default="-", help="输出路径；- 表示 stdout")
    evaluate.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="将 warn 映射为失败退出码 2，不改变产物 verdict",
    )

    safety = sub.add_parser("safety", help="生成运行时安全报告或执行安全门禁")
    safety_sub = safety.add_subparsers(dest="safety_action", required=True)
    for action in ("report", "gate"):
        command = safety_sub.add_parser(action)
        command.add_argument("--run-id", required=True)
        command.add_argument(
            "--suite-id",
            default="agentscope-runtime-safety",
        )
        command.add_argument("--suite-version", default="1.0.0")
        command.add_argument("--output", default="-", help="输出路径；- 表示 stdout")

    compat = sub.add_parser(
        "agentteams-compat",
        help="从版本化 manifest 与观测证据生成 AgentTeams 兼容报告",
    )
    compat.add_argument("--manifest", required=True)
    compat.add_argument("--observation", required=True)
    compat.add_argument("--output", default="-", help="输出路径；- 表示 stdout")

    worker = sub.add_parser("worker", help="运行数据库租约保护的耐久执行 Worker")
    worker.add_argument("--worker-id", default=None)
    worker.add_argument("--once", action="store_true", help="最多领取一个 Job 后退出")
    worker.add_argument("--poll-seconds", type=float, default=None)
    return parser


async def _run_report_command(args: argparse.Namespace) -> int:
    from .bootstrap import ServiceContainer

    container = ServiceContainer.build(get_settings())
    await container.database.initialize_schema()
    try:
        if args.report_kind == "quality":
            quality_report = await container.reporting.quality_report(args.run_id)
            content = (
                quality_report.model_dump_json(indent=2)
                if args.format == "json"
                else container.reporting.render_quality_report(quality_report).content
            )
        else:
            comparison_report = await container.reporting.comparison_report(args.run_id)
            content = (
                comparison_report.model_dump_json(indent=2)
                if args.format == "json"
                else container.reporting.render_comparison_report(comparison_report).content
            )
        _write_output(args.output, content)
        return 0
    except AgentRigError as exc:
        _write_error(exc)
        return 1
    finally:
        await container.database.dispose()


async def _run_gate_command(args: argparse.Namespace) -> int:
    from .bootstrap import ServiceContainer

    try:
        policy = _load_policy(Path(args.policy))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"invalid release policy: {exc}", file=sys.stderr)
        return 64
    container = ServiceContainer.build(get_settings())
    await container.database.initialize_schema()
    try:
        result = await container.release_gates.evaluate(args.run_id, policy)
        content = (
            result.model_dump_json(indent=2)
            if args.format == "json"
            else container.release_gates.render_markdown(result).content
        )
        _write_output(args.output, content)
        return _gate_exit_code(result, fail_on_warn=bool(args.fail_on_warn))
    except AgentRigError as exc:
        _write_error(exc)
        return 1
    finally:
        await container.database.dispose()


async def _run_safety_command(args: argparse.Namespace) -> int:
    from .bootstrap import ServiceContainer

    container = ServiceContainer.build(get_settings())
    await container.database.initialize_schema()
    try:
        if args.safety_action == "report":
            report = await container.safety.report(
                args.run_id,
                suite_id=args.suite_id,
                version=args.suite_version,
            )
            _write_output(args.output, report.model_dump_json(indent=2))
            return 0
        gate = await container.safety.gate(
            args.run_id,
            suite_id=args.suite_id,
            version=args.suite_version,
        )
        _write_output(args.output, gate.model_dump_json(indent=2))
        return _safety_exit_code(gate.outcome)
    except AgentRigError as exc:
        _write_error(exc)
        return 1
    finally:
        await container.database.dispose()


def _run_agentteams_compat_command(args: argparse.Namespace) -> int:
    from .integrations.agentteams.compat import (
        AgentTeamsObservation,
        AgentTeamsProfileManifest,
        adapter_for,
    )

    try:
        manifest = AgentTeamsProfileManifest.model_validate_json(
            Path(args.manifest).read_text(encoding="utf-8")
        )
        observed = AgentTeamsObservation.model_validate_json(
            Path(args.observation).read_text(encoding="utf-8")
        )
        report = adapter_for(manifest).capability_report(
            runtime_observation=observed.runtime,
            skills=observed.skills,
            memberships=observed.memberships,
            invocations=observed.invocations,
            evidence_refs=observed.evidence_refs,
            observed_at=observed.observed_at,
        )
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"invalid AgentTeams compatibility input: {exc}", file=sys.stderr)
        return 64
    _write_output(args.output, report.model_dump_json(indent=2))
    if report.failures:
        return 2
    return 3 if report.limitations else 0


async def _run_worker_command(args: argparse.Namespace) -> int:
    from .bootstrap import ServiceContainer
    from .identifiers import new_id

    settings = get_settings()
    if not settings.execution.durable_scheduler_enabled:
        print(
            "durable worker is disabled; set AGENTRIG_EXECUTION__DURABLE_SCHEDULER_ENABLED=true",
            file=sys.stderr,
        )
        return 64
    poll_seconds = (
        args.poll_seconds
        if args.poll_seconds is not None
        else settings.execution.worker_poll_seconds
    )
    if poll_seconds <= 0 or poll_seconds > 60:
        print("--poll-seconds must be in (0, 60]", file=sys.stderr)
        return 64
    worker_id = args.worker_id or new_id("worker")
    container = ServiceContainer.build(settings)
    await container.initialize()
    try:
        await container.durable_jobs.register_worker(worker_id)
        while True:
            await container.durable_jobs.worker_heartbeat(worker_id)
            await container.durable_worker.recover_expired()
            worked = await container.durable_worker.run_once(worker_id)
            if args.once:
                return 0
            if not worked:
                await asyncio.sleep(poll_seconds)
    except AgentRigError as exc:
        _write_error(exc)
        return 1
    finally:
        await container.durable_jobs.unregister_worker(worker_id)
        await container.close()


def _load_policy(path: Path) -> ReleasePolicy:
    return ReleasePolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _write_output(path: str, content: str) -> None:
    if path == "-":
        print(content)
        return
    Path(path).write_text(f"{content.rstrip()}\n", encoding="utf-8")


def _write_error(exc: AgentRigError) -> None:
    print(exc.detail.model_dump_json(), file=sys.stderr)


def _gate_exit_code(result: ReleaseGateResult, *, fail_on_warn: bool) -> int:
    if result.verdict == "fail" or (result.verdict == "warn" and fail_on_warn):
        return 2
    if result.verdict == "inconclusive":
        return 3
    return 0


def _safety_exit_code(outcome: str) -> int:
    if outcome == "blocked":
        return 2
    if outcome == "inconclusive":
        return 3
    return 0


if __name__ == "__main__":
    main()
