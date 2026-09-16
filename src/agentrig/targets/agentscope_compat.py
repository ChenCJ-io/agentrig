"""Secret-free, versioned live compatibility evidence for AgentScope AG-UI."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from ..canonical import canonical_hash
from .drivers import (
    AgentScopeDriver,
    DriverEventType,
    DriverPrepareContext,
)


class AgentScopeEventEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str | None
    event_type: str
    sequence: int | None
    agent_path: list[str]
    payload_keys: list[str]
    usage_keys: list[str]


class AgentScopeLiveCompatReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agentrig.agentscope-live-compat.v1"] = (
        "agentrig.agentscope-live-compat.v1"
    )
    generated_at: datetime
    endpoint_hash: str
    expected_version: str | None
    observed_version: str | None
    capability_source_status: str
    declared_capabilities: list[str]
    observed_feature_names: list[str]
    events: list[AgentScopeEventEvidence] = Field(default_factory=list)
    terminal_observed: bool
    verdict: Literal["pass", "fail", "inconclusive"]
    limitations: list[str] = Field(default_factory=list)
    result_hash: str


async def collect_agentscope_live_compat(
    endpoint: str,
    *,
    expected_version: str | None = "2.0.6",
    run_path: str = "/agui",
    health_path: str = "/health",
    capability_path: str = "/capabilities",
    message: str = "Return a short compatibility acknowledgement.",
    secret_value: str | None = None,
    timeout_seconds: float = 30,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AgentScopeLiveCompatReport:
    driver = AgentScopeDriver(transport=transport)
    context = DriverPrepareContext(
        case_run_id="agentscope_live_compat",
        target={
            "endpoint": endpoint,
            "options": {
                "run_path": run_path,
                "health_path": health_path,
                "capability_path": capability_path,
                "max_reconnects": 1,
            },
        },
        version=expected_version,
        initial_state={},
        secret_value=secret_value,
        component_timeout_seconds=timeout_seconds,
    )
    limitations: list[str] = []
    events: list[AgentScopeEventEvidence] = []
    capability: dict[str, Any] = {}
    terminal = False
    try:
        session = await driver.prepare(context)
        await driver.probe(context)
        capability = await driver.describe_capabilities(context, session)
        async with asyncio.timeout(timeout_seconds):
            async for event in driver.send_user_message(session, message):
                events.append(
                    AgentScopeEventEvidence(
                        event_id=event.event_id,
                        event_type=event.type.value,
                        sequence=event.sequence,
                        agent_path=event.agent_path,
                        payload_keys=sorted(event.payload),
                        usage_keys=sorted(event.usage),
                    )
                )
                terminal = terminal or event.type is DriverEventType.COMPLETED
                if event.type is DriverEventType.ERROR:
                    limitations.append("runtime_error_event_observed")
        await driver.close(session)
    except TimeoutError:
        limitations.append("live_request_timed_out")
    except httpx.HTTPError as exc:
        limitations.append(f"live_http_failure:{type(exc).__name__}")
    except (TypeError, ValueError) as exc:
        limitations.append(f"live_contract_failure:{type(exc).__name__}")

    runtime_value = capability.get("runtime")
    runtime: dict[str, Any] = runtime_value if isinstance(runtime_value, dict) else {}
    observed_version_value = runtime.get("framework_version")
    observed_version = str(observed_version_value) if observed_version_value else None
    source_status = str(capability.get("source_status") or "unavailable")
    features_value = capability.get("features")
    features: dict[str, Any] = (
        features_value if isinstance(features_value, dict) else {}
    )
    if not terminal:
        limitations.append("terminal_event_not_observed")
    if str(runtime.get("framework") or "") != "agentscope":
        limitations.append("agentscope_runtime_not_observed")
    if expected_version and observed_version and observed_version != expected_version:
        limitations.append("agentscope_version_mismatch")
    if observed_version is None:
        limitations.append("agentscope_version_not_observed")
    if source_status != "observed":
        limitations.append("capability_probe_not_observed")
    limitations = sorted(set(limitations))
    blocking = {
        "runtime_error_event_observed",
        "terminal_event_not_observed",
        "agentscope_runtime_not_observed",
        "agentscope_version_mismatch",
    }
    if any(item in blocking or item.startswith("live_") for item in limitations):
        verdict: Literal["pass", "fail", "inconclusive"] = "fail"
    elif limitations:
        verdict = "inconclusive"
    else:
        verdict = "pass"
    stable = {
        "schema_version": "agentrig.agentscope-live-compat.v1",
        "endpoint_hash": canonical_hash({"endpoint": endpoint.rstrip("/")}),
        "expected_version": expected_version,
        "observed_version": observed_version,
        "capability_source_status": source_status,
        "declared_capabilities": sorted(driver.capabilities().names()),
        "observed_feature_names": sorted(str(key) for key in features),
        "events": [item.model_dump(mode="json") for item in events],
        "terminal_observed": terminal,
        "verdict": verdict,
        "limitations": limitations,
    }
    result_hash = canonical_hash(stable)
    return AgentScopeLiveCompatReport(
        schema_version="agentrig.agentscope-live-compat.v1",
        generated_at=datetime.now(timezone.utc),
        endpoint_hash=canonical_hash({"endpoint": endpoint.rstrip("/")}),
        expected_version=expected_version,
        observed_version=observed_version,
        capability_source_status=source_status,
        declared_capabilities=sorted(driver.capabilities().names()),
        observed_feature_names=sorted(str(key) for key in features),
        events=events,
        terminal_observed=terminal,
        verdict=verdict,
        limitations=limitations,
        result_hash=result_hash,
    )
