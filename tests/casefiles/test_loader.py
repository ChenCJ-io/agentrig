"""项目文件与用例文件的加载、校验和挑选。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentrig.casefiles import CaseFileError, Selection, load_cases, load_project

PROJECT = {
    "version": 1,
    "target": {"entry": "my_app.agent:agent"},
    "initial_state": {"world": {"currency": "CNY", "region": "cn"}},
}


def _write(path: Path, content: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else yaml.safe_dump(content, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path: Path, cases: dict[str, object], **overrides: object) -> Path:
    project_file = _write(tmp_path / "agentrig" / "project.yaml", {**PROJECT, **overrides})
    for name, content in cases.items():
        _write(tmp_path / "agentrig" / "cases" / name, content)
    return project_file


def _case(name: str, *, tags: list[str] | None = None, **extra: object) -> dict[str, object]:
    return {
        "name": name,
        "tags": tags or [],
        "turns": [
            {"user_message": "第一轮", "assertions": [{"kind": "no_execution_error"}]},
            {"user_message": "第二轮"},
        ],
        **extra,
    }


def test_case_files_become_test_cases_with_ids_positions_and_merged_state(tmp_path: Path) -> None:
    project = load_project(
        _project(
            tmp_path,
            {
                "refund/confirm_first.yaml": _case(
                    "退款前必须确认",
                    initial_state={"world": {"region": "us"}, "user": "u1"},
                ),
                "smoke.yml": _case("冒烟", id="smoke-fixed-id"),
            },
        )
    )

    cases = load_cases(project)

    assert project.root == tmp_path.resolve()
    assert [item.case_id for item in cases] == ["refund.confirm_first", "smoke-fixed-id"]
    refund = cases[0].case
    assert [turn.position for turn in refund.turns] == [1, 2]
    assert refund.initial_state == {"world": {"currency": "CNY", "region": "us"}, "user": "u1"}
    assert cases[1].case.initial_state == PROJECT["initial_state"]


def test_all_invalid_files_are_reported_with_one_based_locations(tmp_path: Path) -> None:
    bad_assertion = _case("坏断言")
    bad_assertion["turns"] = [{"user_message": "hi", "assertions": [{"kind": "tool_calld"}]}]
    project = load_project(
        _project(
            tmp_path,
            {
                "a.yaml": bad_assertion,
                "b.yaml": "name: [unclosed\n",
                "c.yaml": "- just\n- a list\n",
                "d.yaml": _case("重复", id="dup"),
                "e.yaml": _case("重复", id="dup"),
            },
        )
    )

    with pytest.raises(CaseFileError) as raised:
        load_cases(project)

    problems = "\n".join(raised.value.problems)
    assert "a.yaml: turns[1].assertions[1].kind" in problems
    assert "b.yaml: 第 2 行 YAML 格式错误" in problems
    assert "c.yaml: 用例文件必须是一个 YAML 对象" in problems
    assert "用例 ID `dup`" in problems


def test_selection_by_path_tag_and_keyword(tmp_path: Path) -> None:
    project = load_project(
        _project(
            tmp_path,
            {
                "refund/a.yaml": _case("退款前必须确认", tags=["p0"]),
                "refund/b.yaml": _case("部分退款", tags=["p1"]),
                "projects/c.yaml": _case("打开项目", tags=["p0"]),
            },
        )
    )
    refund_dir = tmp_path / "agentrig" / "cases" / "refund"

    def ids(selection: Selection) -> list[str]:
        return [item.case_id for item in load_cases(project, selection)]

    assert ids(Selection(paths=(refund_dir,))) == ["refund.a", "refund.b"]
    assert ids(Selection(tags=("p0",))) == ["projects.c", "refund.a"]
    assert ids(Selection(keyword="退款前")) == ["refund.a"]
    assert ids(Selection(paths=(refund_dir,), tags=("p1",))) == ["refund.b"]


def test_project_file_errors_are_reported_before_loading_cases(tmp_path: Path) -> None:
    with pytest.raises(CaseFileError) as missing:
        load_project(tmp_path / "agentrig" / "project.yaml")
    assert "找不到项目文件" in missing.value.problems[0]

    project_file = _write(
        tmp_path / "agentrig" / "project.yaml",
        {"version": 1, "target": {"entry": "a:b", "secret": "sk-plaintext"}, "extra": 1},
    )
    with pytest.raises(CaseFileError) as invalid:
        load_project(project_file)
    problems = "\n".join(invalid.value.problems)
    assert "target.secret" in problems
    assert "extra" in problems
