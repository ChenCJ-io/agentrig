"""把一次本地测试运行渲染成控制台摘要、JUnit XML 与 Markdown。"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree

from .runner import CaseOutcome, TestReport

_MARKS = {"passed": "✓", "failed": "✗", "inconclusive": "?"}
_ICONS = {"passed": "✅", "failed": "❌", "inconclusive": "❔"}
_VERDICTS = {0: "全部通过", 2: "出现回归", 3: "无法判定"}


def render_console(report: TestReport) -> str:
    lines = [
        f"AgentRig · {report.target}@{report.version} · {len(report.outcomes)} 条用例 × "
        f"{report.repeat} 次 · 并发 {report.concurrency}"
    ]
    for outcome in report.outcomes:
        lines.append(
            f"  {_MARKS[outcome.status]} {outcome.case_id}  {outcome.name} · "
            f"{outcome.turns} 轮 · {_seconds(outcome.duration_seconds)}"
        )
        lines.extend(f"      {line}" for line in _details(outcome))
    lines.append(
        f"结果：{report.count('passed')} 通过 · {report.count('failed')} 失败 · "
        f"{report.count('inconclusive')} 无法判定 · 输入 {report.input_tokens:,} token · "
        f"输出 {report.output_tokens:,} token · 用时 {_seconds(report.elapsed_seconds)}"
    )
    lines.append(f"结论：{_VERDICTS[report.exit_code]}（退出码 {report.exit_code}）")
    return "\n".join(lines)


def render_markdown(report: TestReport) -> str:
    lines = [
        "## AgentRig 测试报告",
        "",
        f"`{report.target}@{report.version}` · {len(report.outcomes)} 条用例 × {report.repeat} 次 · "
        f"结论：**{_VERDICTS[report.exit_code]}**（退出码 {report.exit_code}）",
        "",
        "| 结果 | 用例 | 名称 | 轮次 | 用时 |",
        "|---|---|---|---|---|",
    ]
    for outcome in report.outcomes:
        lines.append(
            f"| {_ICONS[outcome.status]} | `{outcome.case_id}` | {_cell(outcome.name)} | "
            f"{outcome.turns} | {_seconds(outcome.duration_seconds)} |"
        )
    problems = [outcome for outcome in report.outcomes if outcome.status != "passed"]
    if problems:
        lines += ["", "### 未通过的用例", ""]
        for outcome in problems:
            lines.append(f"**`{outcome.case_id}`** {outcome.name}（{outcome.path}）")
            lines.append("")
            lines.extend(
                f"  - {line.strip()}" if line.startswith(" ") else f"- {line}"
                for line in _details(outcome)
            )
            lines.append("")
    lines += [
        "",
        f"输入 {report.input_tokens:,} token · 输出 {report.output_tokens:,} token · "
        f"用时 {_seconds(report.elapsed_seconds)} · 运行 `{report.run_id}`",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_junit(report: TestReport) -> str:
    suite_attributes = {
        "name": f"{report.target}@{report.version}",
        "tests": str(len(report.outcomes)),
        "failures": str(report.count("failed")),
        "errors": str(report.count("inconclusive")),
        "time": f"{report.elapsed_seconds:.3f}",
    }
    root = ElementTree.Element("testsuites", {**suite_attributes, "name": "agentrig"})
    suite = ElementTree.SubElement(root, "testsuite", suite_attributes)
    for outcome in report.outcomes:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {
                "classname": report.target,
                "name": outcome.case_id,
                "file": outcome.path,
                "time": f"{outcome.duration_seconds or 0:.3f}",
            },
        )
        if outcome.status == "passed":
            continue
        details = _details(outcome)
        element = ElementTree.SubElement(
            case,
            "failure" if outcome.status == "failed" else "error",
            {"message": details[0] if details else outcome.status},
        )
        element.text = "\n".join(details)
    ElementTree.indent(root)
    body = ElementTree.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="utf-8"?>\n{body}\n'


def _details(outcome: CaseOutcome) -> list[str]:
    lines: list[str] = []
    numbered = len(outcome.attempts) > 1
    for index, attempt in enumerate(outcome.attempts, start=1):
        prefix = f"第 {index} 次：" if numbered else ""
        for failure in attempt.failures:
            lines.append(f"✗ {prefix}{failure.criterion}")
            lines.extend(f"  ← {evidence}" for evidence in failure.evidence)
        if attempt.status == "inconclusive" and attempt.error:
            lines.append(f"? {prefix}{attempt.error}")
    return lines


def _seconds(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(int(value), 60)
    return f"{minutes}m{seconds:02d}s"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
