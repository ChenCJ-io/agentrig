"""发现、加载并挑选仓库里的用例文件。

任何一个文件不合法都集中报告，不会跑一半。用例文件直接用 ``TestCaseCreate`` 校验，与
Web、HTTP、MCP 写入的是同一种用例。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..cases.schemas import TestCaseCreate
from ..targets.options import merge_target_options
from .schemas import ProjectFile

CASE_SUFFIXES = (".yaml", ".yml")
MAX_CASE_ID_LENGTH = 96


class CaseFileError(Exception):
    """一个或多个项目、用例文件不合法；``problems`` 每项都带文件位置。"""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class LoadedProject:
    path: Path
    root: Path
    cases_dir: Path
    config: ProjectFile


@dataclass(frozen=True)
class LoadedCase:
    path: Path
    case: TestCaseCreate

    @property
    def case_id(self) -> str:
        return str(self.case.id)


@dataclass(frozen=True)
class Selection:
    paths: tuple[Path, ...] = ()
    tags: tuple[str, ...] = ()
    keyword: str | None = None


def load_project(path: Path) -> LoadedProject:
    resolved = path.resolve()
    if not resolved.is_file():
        raise CaseFileError([f"{display(path)}: 找不到项目文件"])
    try:
        config = ProjectFile.model_validate(_read_yaml(resolved))
    except ValidationError as exc:
        raise CaseFileError(_validation_problems(resolved, exc)) from exc
    base = resolved.parent
    return LoadedProject(
        path=resolved,
        root=(base / config.root).resolve(),
        cases_dir=(base / config.cases).resolve(),
        config=config,
    )


def load_cases(project: LoadedProject, selection: Selection | None = None) -> list[LoadedCase]:
    """加载选中范围内的全部用例；按标签与名称过滤前先确认每个文件都合法。"""

    selection = selection or Selection()
    problems: list[str] = []
    loaded: list[LoadedCase] = []
    owners: dict[str, Path] = {}
    for path in _discover(project.cases_dir, selection.paths, problems):
        try:
            case = _load_case(path, project)
        except CaseFileError as exc:
            problems.extend(exc.problems)
            continue
        case_id = str(case.id)
        if case_id in owners:
            problems.append(
                f"{display(path)}: 用例 ID `{case_id}` 与 {display(owners[case_id])} 重复"
            )
            continue
        owners[case_id] = path
        loaded.append(LoadedCase(path=path, case=case))
    if problems:
        raise CaseFileError(problems)
    return [item for item in loaded if _selected(item, selection)]


def display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _discover(cases_dir: Path, paths: Iterable[Path], problems: list[str]) -> list[Path]:
    roots = [path.resolve() for path in paths] or [cases_dir]
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root.suffix in CASE_SUFFIXES:
                found.add(root)
            else:
                problems.append(f"{display(root)}: 用例文件必须是 .yaml 或 .yml")
        elif root.is_dir():
            found.update(
                item for item in root.rglob("*") if item.is_file() and item.suffix in CASE_SUFFIXES
            )
        else:
            problems.append(f"{display(root)}: 路径不存在")
    return sorted(found)


def _load_case(path: Path, project: LoadedProject) -> TestCaseCreate:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise CaseFileError([f"{display(path)}: 用例文件必须是一个 YAML 对象"])
    document = dict(data)
    if document.get("id") is None:
        case_id = _case_id(path, project.cases_dir)
        if len(case_id) > MAX_CASE_ID_LENGTH:
            raise CaseFileError(
                [f"{display(path)}: 由路径生成的用例 ID 超过 {MAX_CASE_ID_LENGTH} 个字符，请写 id 字段"]
            )
        document["id"] = case_id
    turns = document.get("turns")
    if isinstance(turns, list):
        # 轮次的先后顺序就是 position，文件里不必手写。
        document["turns"] = [
            {"position": index, **turn} if isinstance(turn, dict) and "position" not in turn else turn
            for index, turn in enumerate(turns, start=1)
        ]
    state = document.get("initial_state")
    if state is None or isinstance(state, dict):
        document["initial_state"] = merge_target_options(
            project.config.initial_state,
            state or {},
        )
    try:
        return TestCaseCreate.model_validate(document)
    except ValidationError as exc:
        raise CaseFileError(_validation_problems(path, exc)) from exc


def _case_id(path: Path, cases_dir: Path) -> str:
    try:
        relative = path.relative_to(cases_dir)
    except ValueError:
        relative = Path(path.name)
    return ".".join(relative.with_suffix("").parts)


def _selected(item: LoadedCase, selection: Selection) -> bool:
    if selection.tags and not set(selection.tags) & set(item.case.tags):
        return False
    if selection.keyword:
        keyword = selection.keyword.casefold()
        haystack = f"{item.case_id} {item.case.name}".casefold()
        if keyword not in haystack:
            return False
    return True


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" 第 {mark.line + 1} 行" if mark is not None else ""
        raise CaseFileError([f"{display(path)}:{where} YAML 格式错误：{exc}"]) from exc
    except OSError as exc:
        raise CaseFileError([f"{display(path)}: 无法读取：{exc}"]) from exc


def _validation_problems(path: Path, exc: ValidationError) -> list[str]:
    return [
        f"{display(path)}: {_location(error['loc'])}: {error['msg']}"
        for error in exc.errors(include_url=False)
    ]


def _location(parts: tuple[int | str, ...]) -> str:
    """``('turns', 0, 'assertions', 1)`` → ``turns[1].assertions[2]``，序号从 1 开始。"""

    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part + 1}]"
        else:
            text += f".{part}" if text else str(part)
    return text or "(文件)"
