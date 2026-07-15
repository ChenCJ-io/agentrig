"""discovery / results / verdict / observability 工具组测试。"""
from __future__ import annotations

from agentrig.api import _runs
from agentrig.mcp_tools.discovery import get_case_schema_impl, list_agentrig_tools_impl
from agentrig.mcp_tools.observability import list_traces_impl
from agentrig.mcp_tools.results import list_runs_impl
from agentrig.mcp_tools.verdict import get_verdict_impl
from agentrig.proxy.trace import TraceEntry
from agentrig.runtime import get_runtime, reset_runtime


def test_discovery_lists_tools_and_schema() -> None:
    tools = list_agentrig_tools_impl()
    assert any(t["name"] == "run_single_case" for t in tools)
    assert any(t["group"] == "discovery" for t in tools)
    schema = get_case_schema_impl()
    assert "id" in schema and "user_message" in schema and "judge_mode" in schema


def test_results_reflects_runs() -> None:
    _runs.clear()
    _runs.append({"id": "AR-1", "scope": "c1", "passed": 1, "failed": 0})
    runs = list_runs_impl()
    assert runs[0]["id"] == "AR-1"
    _runs.clear()


def test_verdict_no_run_returns_hint() -> None:
    _runs.clear()
    r = get_verdict_impl("missing")
    assert isinstance(r, str) and "no run" in r


def test_verdict_finds_case() -> None:
    _runs.clear()
    _runs.append({"id": "AR-2", "scope": "c2", "passed": 0, "failed": 1})
    v = get_verdict_impl("c2")
    assert isinstance(v, dict)
    assert v["passed"] is False
    _runs.clear()


def test_observability_traces() -> None:
    reset_runtime()
    rt = get_runtime()
    rt.trace.entries.append(TraceEntry("echo__echo", {"x": 1}, source="real"))
    traces = list_traces_impl()
    assert len(traces) == 1
    assert traces[0]["tool"] == "echo__echo"
    assert traces[0]["source"] == "real"
    assert list_traces_impl("other") == []
    reset_runtime()
