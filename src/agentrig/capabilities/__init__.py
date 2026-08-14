"""Target runtime capability snapshots and deterministic comparison."""

from .schemas import (
    CapabilityComparison,
    CapabilityComparisonPolicy,
    CapabilityDiff,
    CapabilitySourceStatus,
    TargetCapabilitySnapshot,
)
from .service import (
    build_declared_snapshot,
    build_legacy_snapshot,
    compare_capabilities,
    merge_observed_capabilities,
)

__all__ = [
    "CapabilityComparison",
    "CapabilityComparisonPolicy",
    "CapabilityDiff",
    "CapabilitySourceStatus",
    "TargetCapabilitySnapshot",
    "build_declared_snapshot",
    "build_legacy_snapshot",
    "compare_capabilities",
    "merge_observed_capabilities",
]
