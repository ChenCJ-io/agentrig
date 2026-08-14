"""Opt-in live AgentScope 2.0.6 AG-UI compatibility acceptance."""

from __future__ import annotations

import os

import pytest

from agentrig.targets.agentscope_compat import collect_agentscope_live_compat

ENDPOINT = os.environ.get("AGENTRIG_TEST_AGENTSCOPE_AGUI_URL")
pytestmark = pytest.mark.skipif(
    not ENDPOINT,
    reason="AGENTRIG_TEST_AGENTSCOPE_AGUI_URL is not configured",
)


async def test_agentscope_agui_live_report_passes() -> None:
    report = await collect_agentscope_live_compat(
        ENDPOINT or "",
        expected_version=os.environ.get("AGENTRIG_TEST_AGENTSCOPE_VERSION", "2.0.6"),
        run_path=os.environ.get("AGENTRIG_TEST_AGENTSCOPE_RUN_PATH", "/agui"),
        health_path=os.environ.get("AGENTRIG_TEST_AGENTSCOPE_HEALTH_PATH", "/health"),
        capability_path=os.environ.get(
            "AGENTRIG_TEST_AGENTSCOPE_CAPABILITY_PATH",
            "/capabilities",
        ),
        secret_value=os.environ.get("AGENTRIG_TEST_AGENTSCOPE_TOKEN"),
        timeout_seconds=float(os.environ.get("AGENTRIG_TEST_AGENTSCOPE_TIMEOUT", "30")),
    )

    assert report.verdict == "pass", report.model_dump(mode="json")
