"""ExecutionProfile 的稳定枚举。"""

from enum import StrEnum


class ToolMode(StrEnum):
    CONTROLLED = "controlled"
    PROXY = "proxy"
    OBSERVE_ONLY = "observe_only"


class ProviderName(StrEnum):
    FIXTURE = "fixture"
    SAMPLE = "sample"
    SIMULATION_CURATOR = "simulation_curator"
    REAL_TOOL = "real_tool"
