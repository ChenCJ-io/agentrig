"""``agentrig test``：读取仓库里的用例文件，在进程内跑完并给出退出码。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from .loader import CaseFileError, Selection, display, load_cases, load_project

if TYPE_CHECKING:
    from ..agents.model_client import ModelClient

EXIT_CONFIG_ERROR = 1
EXIT_INCONCLUSIVE = 3


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("test", help="运行仓库里的用例文件（AR-RFC-0006）")
    parser.add_argument("paths", nargs="*", help="只运行这些文件或目录下的用例")
    parser.add_argument(
        "--config",
        default="agentrig/project.yaml",
        help="项目文件，默认 agentrig/project.yaml",
    )
    parser.add_argument("--tag", action="append", default=[], help="只运行带这个标签的用例，可重复")
    parser.add_argument("-k", dest="keyword", help="只运行 ID 或名称包含这段文字的用例")
    parser.add_argument(
        "--no-curator",
        action="store_true",
        help="严格模式：只用 Fixture/Sample，不需要模型 Key",
    )
    parser.add_argument("--concurrency", type=int, help="覆盖 profile.concurrency")
    parser.add_argument("--repeat", type=int, help="覆盖 profile.repeat")
    parser.add_argument("--junit", help="写出 JUnit XML")
    parser.add_argument("--markdown", help="写出 Markdown 报告")
    parser.add_argument(
        "--keep-db",
        help="把本次运行的 SQLite 保存到这个路径（已存在会被覆盖），可用 agentrig serve 查看",
    )


def run_test_command(
    args: argparse.Namespace,
    *,
    model_client: ModelClient | None = None,
) -> int:
    # 执行链会装配整个服务，按需导入，其他子命令的启动不受影响。
    from ..errors import AgentRigError
    from .report import render_console, render_junit, render_markdown
    from .runner import (
        TargetUnavailableError,
        effective_providers,
        execute,
        preflight_problems,
        resolve_target,
    )

    try:
        project = load_project(Path(args.config))
        cases = load_cases(
            project,
            Selection(
                paths=tuple(Path(item) for item in args.paths),
                tags=tuple(args.tag),
                keyword=args.keyword,
            ),
        )
    except CaseFileError as exc:
        _report_problems("用例文件不合法", exc.problems)
        return EXIT_CONFIG_ERROR
    if not cases:
        print("没有选中任何用例。", file=sys.stderr)
        return EXIT_INCONCLUSIVE
    profile = project.config.profile
    providers = effective_providers(project, no_curator=args.no_curator)
    problems = preflight_problems(project, cases, providers)
    for value, flag in ((args.concurrency, "--concurrency"), (args.repeat, "--repeat")):
        if value is not None and value < 1:
            problems.append(f"{flag} 必须大于 0")
    if problems:
        _report_problems("无法开始运行", problems)
        return EXIT_CONFIG_ERROR
    target = resolve_target(project)
    try:
        with _database(args.keep_db) as database_url:
            _migrate(database_url)
            report = asyncio.run(
                execute(
                    cases,
                    project=project,
                    target=target,
                    providers=providers,
                    database_url=database_url,
                    concurrency=args.concurrency or profile.concurrency,
                    repeat=args.repeat or profile.repeat,
                    model_client=model_client,
                )
            )
    except TargetUnavailableError as exc:
        _report_problems("被测 Agent 无法启动", [str(exc)])
        return EXIT_CONFIG_ERROR
    except AgentRigError as exc:
        _report_problems("配置无效", [exc.detail.message])
        return EXIT_CONFIG_ERROR
    print(render_console(report))
    if args.junit:
        _write(Path(args.junit), render_junit(report))
    if args.markdown:
        _write(Path(args.markdown), render_markdown(report))
    if args.keep_db:
        path = Path(args.keep_db).resolve()
        print(
            f"数据库已保存到 {display(path)}；查看证据："
            f"AGENTRIG_DATABASE__URL=sqlite+aiosqlite:///{path} agentrig serve"
        )
    return report.exit_code


@contextmanager
def _database(keep_db: str | None) -> Iterator[str]:
    if keep_db:
        path = Path(keep_db).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        yield f"sqlite+aiosqlite:///{path}"
        return
    with tempfile.TemporaryDirectory(prefix="agentrig-test-") as directory:
        yield f"sqlite+aiosqlite:///{Path(directory) / 'agentrig.db'}"


def _migrate(database_url: str) -> None:
    """按正式迁移建库，保留下来的库可以直接交给 ``agentrig serve``。"""

    from alembic import command

    from ..infrastructure.database.migrations import migration_config

    previous = os.environ.get("AGENTRIG_DATABASE__URL")
    os.environ["AGENTRIG_DATABASE__URL"] = database_url
    try:
        with migration_config() as config:
            # 不按 alembic.ini 配置日志，测试输出只保留结论。
            config.config_file_name = None
            command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("AGENTRIG_DATABASE__URL", None)
        else:
            os.environ["AGENTRIG_DATABASE__URL"] = previous


def _report_problems(title: str, problems: list[str]) -> None:
    print(f"{title}：", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
