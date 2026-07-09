"""AgentRig 测试的共享 pytest fixture。"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_agent_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认清空 AGENTRIG_AGENT__SERVER_URL，保证 execution 默认降级 echo。

    避免开发机的该环境变量污染降级模式测试；需要真实模式的测试在测试体内
    自行 monkeypatch.setenv。
    """
    monkeypatch.delenv("AGENTRIG_AGENT__SERVER_URL", raising=False)
