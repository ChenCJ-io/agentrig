"""``agentrig test`` 端到端：仓库里的用例文件 → 进程内运行 → 报告与退出码。"""

from __future__ import annotations

import asyncio
import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentrig.agents.model_client import ModelOutput
from agentrig.casefiles.command import run_test_command
from agentrig.cli import _build_parser, main
from agentrig.infrastructure.database import Database

AGENTS = Path(__file__).resolve().parents[1] / "sdk" / "agents"
CONFIRM_FIRST = {
    "name": "退款前必须确认",
    "tags": ["refund", "p0"],
    "turns": [
        {
            "user_message": "订单 A123 帮我退款",
            "fixtures": [
                {
                    "tool_name": "lookup_order",
                    "match_arguments": {"order_id": "A123"},
                    "result": {"order_id": "A123", "amount": 199},
                },
                {"tool_name": "issue_refund", "result": {"refund_id": "r_1"}},
            ],
            "assertions": [
                {"kind": "tool_called", "tool_name": "lookup_order"},
                {"kind": "tool_not_called", "tool_name": "issue_refund"},
                {"kind": "text_contains", "value": "请确认"},
            ],
        }
    ],
}


def _repo(
    tmp_path: Path,
    *,
    version: str = "baseline",
    entry: str = "refund_agent.py:run",
    profile: dict[str, Any] | None = None,
    cases: dict[str, Any] | None = None,
) -> Path:
    project_dir = tmp_path / "agentrig"
    project = {
        "version": 1,
        "target": {
            "name": "refund-bot",
            "entry": str(AGENTS / entry.split(":")[0]) + ":" + entry.split(":")[1],
            "python": sys.executable,
            "version": version,
        },
        "profile": profile or {"providers": ["fixture"], "concurrency": 2},
    }
    project_dir.mkdir(parents=True)
    (project_dir / "project.yaml").write_text(yaml.safe_dump(project, allow_unicode=True))
    for name, content in (cases or {"refund/confirm_first.yaml": CONFIRM_FIRST}).items():
        path = project_dir / "cases" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content, allow_unicode=True), encoding="utf-8")
    return project_dir / "project.yaml"


def _run(*argv: str) -> int:
    with pytest.raises(SystemExit) as raised:
        main(["test", *argv])
    return int(raised.value.code or 0)


def test_passing_suite_writes_reports_and_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _repo(tmp_path)
    junit = tmp_path / "out" / "junit.xml"
    markdown = tmp_path / "out" / "report.md"

    code = _run("--config", str(config), "--junit", str(junit), "--markdown", str(markdown))

    output = capsys.readouterr().out
    assert code == 0
    assert "✓ refund.confirm_first" in output
    assert "结论：全部通过（退出码 0）" in output
    suite = ElementTree.parse(junit).getroot().find("testsuite")
    assert suite is not None and suite.get("tests") == "1" and suite.get("failures") == "0"
    assert "✅ | `refund.confirm_first`" in markdown.read_text(encoding="utf-8")


def test_regression_exits_two_and_points_at_the_offending_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _repo(tmp_path, version="candidate-regression")
    markdown = tmp_path / "report.md"

    code = _run("--config", str(config), "--markdown", str(markdown))

    output = capsys.readouterr().out
    assert code == 2
    assert "✗ refund.confirm_first" in output
    assert "tool_not_called: issue_refund in turn 1" in output
    assert '第 1 轮调用 issue_refund {"order_id": "A123", "amount": 199}，结果来自 fixture' in output
    report = markdown.read_text(encoding="utf-8")
    assert "结论：**出现回归**（退出码 2）" in report
    assert "### 未通过的用例" in report


def test_strict_mode_without_fixture_is_inconclusive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AGENTRIG_TEST_CURATOR_KEY", raising=False)
    case = json.loads(json.dumps(CONFIRM_FIRST))
    case["turns"][0]["fixtures"] = case["turns"][0]["fixtures"][:1]
    config = _repo(
        tmp_path,
        version="candidate-regression",
        profile={
            "curator": {
                "base_url": "https://model.example/v1",
                "model": "model-name",
                "secret": "env:AGENTRIG_TEST_CURATOR_KEY",
            }
        },
        cases={"refund.yaml": case},
    )

    assert _run("--config", str(config)) == 1
    assert "AGENTRIG_TEST_CURATOR_KEY" in capsys.readouterr().err

    code = _run("--config", str(config), "--no-curator")

    output = capsys.readouterr().out
    assert code == 3
    assert "? refund" in output
    assert "provider_exhausted" in output


def test_curator_fills_missing_fixtures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTRIG_TEST_CURATOR_KEY", "test-key")
    case = json.loads(json.dumps(CONFIRM_FIRST))
    case["turns"][0]["fixtures"] = case["turns"][0]["fixtures"][:1]
    case["turns"][0]["assertions"] = [
        {"kind": "tool_called", "tool_name": "issue_refund"},
        {"kind": "text_contains", "value": "sim_1"},
    ]
    config = _repo(
        tmp_path,
        version="candidate-regression",
        profile={
            "curator": {
                "base_url": "https://model.example/v1",
                "model": "model-name",
                "secret": "env:AGENTRIG_TEST_CURATOR_KEY",
            }
        },
        cases={"refund.yaml": case},
    )

    class CuratorStub:
        async def generate_json(self, **request: Any) -> ModelOutput:
            return ModelOutput(
                value={"result": {"refund_id": "sim_1"}, "state_updates": {}},
                raw_text="{}",
                metadata={"model": "curator-stub"},
            )

    args = _build_parser().parse_args(["test", "--config", str(config)])
    code = run_test_command(args, model_client=CuratorStub())

    assert code == 0
    assert "✓ refund" in capsys.readouterr().out


def test_configuration_problems_exit_one_before_running(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid = json.loads(json.dumps(CONFIRM_FIRST))
    invalid["turns"][0]["assertions"][0]["kind"] = "tool_calld"
    config = _repo(tmp_path / "invalid", cases={"bad.yaml": invalid})
    assert _run("--config", str(config)) == 1
    assert "turns[1].assertions[1].kind" in capsys.readouterr().err

    broken = _repo(tmp_path / "broken", entry="broken_agent.py:run")
    assert _run("--config", str(broken)) == 1
    assert "被测 Agent 无法启动" in capsys.readouterr().err

    assert _run("--config", str(_repo(tmp_path / "empty")), "--tag", "missing") == 3
    assert "没有选中任何用例" in capsys.readouterr().err


def test_kept_database_is_migrated_for_agentrig_serve(tmp_path: Path) -> None:
    config = _repo(tmp_path)
    kept = tmp_path / "state" / "test.db"

    assert _run("--config", str(config), "--keep-db", str(kept)) == 0

    async def schema_is_current() -> None:
        database = Database(f"sqlite+aiosqlite:///{kept}")
        try:
            await database.require_current_schema()
        finally:
            await database.dispose()

    asyncio.run(schema_is_current())
