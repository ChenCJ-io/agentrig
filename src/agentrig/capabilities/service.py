"""Pure snapshot canonicalization, observed merge, and A/B comparison."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..canonical import canonical_hash
from ..identifiers import new_id
from .schemas import (
    CapabilityComparison,
    CapabilityComparisonPolicy,
    CapabilityDiff,
    CapabilityDifference,
    CapabilityFeature,
    CapabilityPartitionHashes,
    CapabilitySource,
    TargetCapabilitySnapshot,
)

if TYPE_CHECKING:
    from ..targets.drivers.base import DriverCapabilities

_PARTITIONS = (
    "runtime",
    "model",
    "tools",
    "skills",
    "permissions",
    "workspace",
    "memory",
    "collaboration",
)


def build_declared_snapshot(
    *,
    case_run_id: str,
    target: dict[str, Any],
    profile: dict[str, Any],
    driver_capabilities: DriverCapabilities,
    collected_at: datetime | None = None,
) -> TargetCapabilitySnapshot:
    options = dict(target.get("options") or {})
    safe_target = {
        "id": target.get("id"),
        "driver_type": target.get("driver_type"),
        "version": target.get("version"),
        "options": _public_options(options),
    }
    runtime_value = dict(options.get("runtime") or {})
    runtime = {
        "framework": runtime_value.get("framework") or target.get("driver_type"),
        "framework_version": (
            runtime_value.get("framework_version")
            or options.get("framework_version")
            or "unversioned"
        ),
        "service_version": runtime_value.get("service_version"),
        "protocol": runtime_value.get("protocol") or target.get("driver_type"),
        "protocol_version": runtime_value.get("protocol_version"),
        "image_digest": runtime_value.get("image_digest"),
        "source_status": "declared",
    }
    models = _normalized_items(options.get("models"), identity_keys=("role", "model_id"))
    tools = _normalized_tools(options.get("tool_catalog") or options.get("tools"))
    skills = _normalized_items(options.get("skills"), identity_keys=("id", "name"))
    permissions = {
        "mode": options.get("permission_mode") or profile.get("tool_mode"),
        "real_tool_enabled": any(
            str(item.get("name")) == "real_tool"
            for item in profile.get("provider_chain", [])
            if isinstance(item, dict)
        ),
        "source_status": "declared",
    }
    workspace = _content_safe_mapping(options.get("workspace"))
    memory = _content_safe_mapping(options.get("memory"))
    collaboration = _content_safe_mapping(options.get("collaboration"))
    features = {
        name: CapabilityFeature(
            status="declared" if enabled else "unsupported",
            value=bool(enabled),
        )
        for name, enabled in driver_capabilities.model_dump().items()
    }
    missing = ["runtime.observation"]
    return _snapshot(
        snapshot_id=new_id("capsnap"),
        case_run_id=case_run_id,
        collected_at=collected_at or datetime.now(timezone.utc),
        collection_status="partial",
        source=CapabilitySource(
            driver=str(target.get("driver_type") or "unknown"),
            target_config_hash=canonical_hash(safe_target),
        ),
        runtime=runtime,
        models=models,
        tools=tools,
        skills=skills,
        permissions=permissions,
        workspace=workspace,
        memory=memory,
        collaboration=collaboration,
        features=features,
        missing_fields=missing,
        limitations=["runtime_probe_not_observed"],
    )


def build_legacy_snapshot(
    *,
    case_run_id: str,
    target: dict[str, Any],
    collected_at: datetime | None = None,
) -> TargetCapabilitySnapshot:
    """Represent missing historical evidence without reconstructing current state."""

    safe_target = {
        "id": target.get("id"),
        "driver_type": target.get("driver_type"),
        "version": target.get("version"),
    }
    return _snapshot(
        snapshot_id=f"legacy:{case_run_id}",
        case_run_id=case_run_id,
        collected_at=collected_at or datetime.fromtimestamp(0, tz=timezone.utc),
        collection_status="legacy_unavailable",
        source=CapabilitySource(
            driver=str(target.get("driver_type") or "unknown"),
            target_config_hash=canonical_hash(safe_target),
        ),
        runtime={},
        models=[],
        tools=[],
        skills=[],
        permissions={},
        workspace={},
        memory={},
        collaboration={},
        features={},
        missing_fields=["legacy.capability_snapshot"],
        limitations=["historical_capability_snapshot_not_recorded"],
    )


def merge_observed_capabilities(
    snapshot: TargetCapabilitySnapshot,
    observed: dict[str, Any],
    *,
    collected_at: datetime | None = None,
) -> TargetCapabilitySnapshot:
    """Merge a driver probe without upgrading unverified claims to verified."""

    runtime = {
        **snapshot.runtime,
        **_content_safe_mapping(observed.get("runtime")),
    }
    runtime["source_status"] = str(
        observed.get("source_status") or runtime.get("source_status") or "observed"
    )
    features = dict(snapshot.features)
    for name, raw in _safe_mapping(observed.get("features")).items():
        if isinstance(raw, dict):
            status = str(raw.get("status") or "observed")
            value = raw.get("value")
            refs = raw.get("evidence_refs") or []
        else:
            status = "observed"
            value = raw
            refs = []
        if status not in {"declared", "observed", "verified", "unsupported", "unknown"}:
            status = "unknown"
        features[name] = CapabilityFeature(
            status=status,  # type: ignore[arg-type]
            value=value if isinstance(value, (bool, str, int, float)) or value is None else None,
            evidence_refs=[str(item) for item in refs],
        )
    values = {
        "runtime": runtime,
        "models": _observed_or_existing(observed, "models", snapshot.models),
        "tools": _observed_or_existing(observed, "tools", snapshot.tools),
        "skills": _observed_or_existing(observed, "skills", snapshot.skills),
        "permissions": {
            **snapshot.permissions,
            **_safe_mapping(observed.get("permissions")),
        },
        "workspace": {
            **snapshot.workspace,
            **_content_safe_mapping(observed.get("workspace")),
        },
        "memory": {
            **snapshot.memory,
            **_content_safe_mapping(observed.get("memory")),
        },
        "collaboration": {
            **snapshot.collaboration,
            **_content_safe_mapping(observed.get("collaboration")),
        },
    }
    missing = [
        item
        for item in snapshot.missing_fields
        if not (
            item == "runtime.observation"
            and runtime.get("source_status") in {"observed", "verified"}
        )
        and not _path_has_value(values, item)
    ]
    limitations = [
        item for item in snapshot.limitations if item != "runtime_probe_not_observed"
    ]
    if missing:
        limitations.append("runtime_probe_partial")
    return _snapshot(
        snapshot_id=snapshot.snapshot_id,
        case_run_id=snapshot.case_run_id,
        collected_at=collected_at or datetime.now(timezone.utc),
        collection_status="partial" if missing else "complete",
        source=snapshot.source,
        runtime=values["runtime"],
        models=values["models"],
        tools=values["tools"],
        skills=values["skills"],
        permissions=values["permissions"],
        workspace=values["workspace"],
        memory=values["memory"],
        collaboration=values["collaboration"],
        features=features,
        missing_fields=missing,
        limitations=sorted(set(limitations)),
    )


def compare_capabilities(
    baseline: TargetCapabilitySnapshot | None,
    candidate: TargetCapabilitySnapshot | None,
    policy: CapabilityComparisonPolicy | None = None,
) -> CapabilityDiff:
    resolved_policy = policy or CapabilityComparisonPolicy()
    comparison: CapabilityComparison
    if baseline is None or candidate is None:
        comparison = (
            "incomparable_environment"
            if resolved_policy.unknown_is_incomparable
            else "unknown"
        )
        return CapabilityDiff(
            baseline_snapshot_hash=baseline.snapshot_hash if baseline else None,
            candidate_snapshot_hash=candidate.snapshot_hash if candidate else None,
            comparison=comparison,
            limitations=["capability_snapshot_missing"],
        )
    unavailable_statuses = {
        "partial",
        "unavailable",
        "invalid",
        "legacy_unavailable",
    }
    if (
        baseline.collection_status in unavailable_statuses
        or candidate.collection_status in unavailable_statuses
        or baseline.missing_fields
        or candidate.missing_fields
    ):
        comparison = (
            "incomparable_environment"
            if resolved_policy.unknown_is_incomparable
            else "unknown"
        )
        return CapabilityDiff(
            baseline_snapshot_hash=baseline.snapshot_hash,
            candidate_snapshot_hash=candidate.snapshot_hash,
            comparison=comparison,
            limitations=["blocking_capability_fields_unknown"],
        )
    differences: list[CapabilityDifference] = []
    allowed = set(resolved_policy.allowed_differences)
    baseline_hashes = baseline.partition_hashes.model_dump()
    candidate_hashes = candidate.partition_hashes.model_dump()
    for partition in _PARTITIONS:
        key = f"{partition}_hash"
        if baseline_hashes[key] == candidate_hashes[key]:
            continue
        is_allowed = partition in allowed or f"{partition}.*" in allowed
        blocking = partition in resolved_policy.blocking_partitions and not is_allowed
        differences.append(
            CapabilityDifference(
                path=partition,
                baseline_hash=baseline_hashes[key],
                candidate_hash=candidate_hashes[key],
                severity="blocking" if blocking else "warning",
                allowed=is_allowed,
                reason=(
                    "difference explicitly allowed by comparison policy"
                    if is_allowed
                    else "capability partition hash changed"
                ),
            )
        )
    if any(item.severity == "blocking" for item in differences):
        comparison = "incomparable_environment"
    elif differences:
        comparison = "warning_difference"
    else:
        comparison = "comparable"
    return CapabilityDiff(
        baseline_snapshot_hash=baseline.snapshot_hash,
        candidate_snapshot_hash=candidate.snapshot_hash,
        comparison=comparison,
        differences=differences,
        limitations=[],
    )


def _snapshot(**values: Any) -> TargetCapabilitySnapshot:
    partitions = {
        "runtime": values["runtime"],
        "model": values["models"],
        "tools": values["tools"],
        "skills": values["skills"],
        "permissions": values["permissions"],
        "workspace": values["workspace"],
        "memory": values["memory"],
        "collaboration": values["collaboration"],
    }
    hashes = CapabilityPartitionHashes(
        **{f"{name}_hash": canonical_hash(value) for name, value in partitions.items()}
    )
    stable = {
        "schema_version": "agentrig.target-capability-snapshot.v1",
        "source": values["source"].model_dump(mode="json"),
        **partitions,
        "features": {
            key: value.model_dump(mode="json")
            for key, value in sorted(values["features"].items())
        },
        "missing_fields": sorted(values["missing_fields"]),
        "limitations": sorted(values["limitations"]),
        "partition_hashes": hashes.model_dump(mode="json"),
    }
    return TargetCapabilitySnapshot(
        **values,
        partition_hashes=hashes,
        snapshot_hash=canonical_hash(stable),
    )


def _public_options(options: dict[str, Any]) -> dict[str, Any]:
    forbidden = {
        "authorization",
        "cookie",
        "credential",
        "credential_ref",
        "secret",
        "secret_ref",
        "token",
        "api_key",
        "request_headers",
    }
    return {
        str(key): _public_value(value)
        for key, value in sorted(options.items())
        if str(key).casefold().replace("-", "_") not in forbidden
    }


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _public_options(value)
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


def _safe_mapping(value: Any) -> dict[str, Any]:
    return _public_options(value) if isinstance(value, dict) else {}


def _content_safe_mapping(value: Any) -> dict[str, Any]:
    """Keep capability metadata while excluding runtime and artifact bodies."""

    forbidden = {
        "body",
        "bytes",
        "content",
        "data",
        "memory",
        "message",
        "messages",
        "reasoning",
        "thinking",
        "value",
    }
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _content_safe_value(item, forbidden)
        for key, item in sorted(value.items())
        if str(key).casefold().replace("-", "_") not in forbidden
    }


def _content_safe_value(value: Any, forbidden: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _content_safe_value(item, forbidden)
            for key, item in sorted(value.items())
            if str(key).casefold().replace("-", "_") not in forbidden
        }
    if isinstance(value, list):
        return [_content_safe_value(item, forbidden) for item in value]
    return _public_value(value)


def _normalized_items(value: Any, *, identity_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items = [_safe_mapping(item) for item in value if isinstance(item, dict)]
    return sorted(
        items,
        key=lambda item: tuple(str(item.get(key) or "") for key in identity_keys),
    )


def _normalized_tools(value: Any) -> list[dict[str, Any]]:
    tools = _normalized_items(value, identity_keys=("name",))
    return [
        {
            "name": item.get("name"),
            "namespace": item.get("namespace"),
            "description_hash": canonical_hash(str(item.get("description") or "").strip()),
            "input_schema_hash": canonical_hash(
                item.get("inputSchema") or item.get("input_schema") or {}
            ),
            "output_schema_hash": canonical_hash(
                item.get("outputSchema") or item.get("output_schema") or {}
            ),
            "execution_mode": item.get("execution_mode"),
            "source_status": item.get("source_status") or "declared",
        }
        for item in tools
    ]


def _observed_or_existing(
    observed: dict[str, Any],
    key: str,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    value = observed.get(key)
    if not isinstance(value, list):
        return existing
    if key == "tools":
        return _normalized_tools(
            [
                {
                    **item,
                    "source_status": item.get("source_status") or "observed",
                }
                for item in value
                if isinstance(item, dict)
            ]
        )
    if key == "models":
        return _normalized_items(value, identity_keys=("role", "model_id"))
    if key == "skills":
        return _normalized_items(value, identity_keys=("id", "name"))
    return sorted(
        [_safe_mapping(item) for item in value if isinstance(item, dict)],
        key=lambda item: canonical_hash(item),
    )


def _path_has_value(values: dict[str, Any], path: str) -> bool:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is not None
