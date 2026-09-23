"""agentrig.sdk 运行在被测解释器里：只能依赖标准库，并保持 Python 3.10 语法兼容。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import agentrig.sdk

SDK_ROOT = Path(agentrig.sdk.__file__).parent
# 只允许在函数体内按需导入的可选依赖：被测环境里通常已有，缺失时适配器自行降级。
LAZY_OPTIONAL_IMPORTS = {"agno", "langchain", "langchain_core", "langgraph", "pydantic"}


def _sources() -> list[Path]:
    return sorted(SDK_ROOT.rglob("*.py"))


def _absolute_roots(nodes: list[ast.stmt]) -> set[str]:
    roots: set[str] = set()
    for node in nodes:
        for item in ast.walk(node):
            if isinstance(item, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in item.names)
            elif isinstance(item, ast.ImportFrom) and item.level == 0 and item.module:
                roots.add(item.module.split(".", 1)[0])
    return roots


def test_sdk_module_level_imports_are_stdlib_only() -> None:
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_level = [
            node
            for node in tree.body
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        functions = [node for node in tree.body if node not in module_level]
        assert _absolute_roots(module_level) <= allowed, path
        assert _absolute_roots(functions) <= allowed | LAZY_OPTIONAL_IMPORTS, path


def test_sdk_sources_parse_as_python_310() -> None:
    for path in _sources():
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 10))
