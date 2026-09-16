"""AgentScope 2.x service profile layered on the AG-UI transport."""

from __future__ import annotations

from typing import Any, cast

import httpx

from .ag_ui import AgUiDriver
from .base import DriverCapabilities, DriverPrepareContext, DriverSession


class AgentScopeDriver(AgUiDriver):
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            streaming=True,
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            session_resume=True,
            usage_metrics=True,
            full_trace=True,
            tool_proxy_injection=True,
            permission_observation=True,
            permission_response=True,
            interrupt=True,
            resume=True,
            external_execution=True,
            nested_agents=True,
            model_call_observation=True,
            memory_observation=True,
            workspace_artifacts=True,
            multimodal=True,
            ordered_event_cursor=True,
        )

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, Any]:
        declared = await super().describe_capabilities(context, session)
        options = session.state["options"]
        path = str(options.get("capability_path") or "/capabilities")
        if options.get("capability_probe", True) is False:
            declared["runtime"]["framework"] = "agentscope"
            return declared
        url = f"{session.state['root_endpoint']}{path}"
        try:
            async with httpx.AsyncClient(**self._client_options(session)) as client:
                response = await client.get(url, headers=session.state["headers"])
                response.raise_for_status()
                observed = response.json()
        except (httpx.HTTPError, ValueError):
            declared["runtime"]["framework"] = "agentscope"
            declared["limitations"] = ["agentscope_capability_endpoint_unavailable"]
            return declared
        if not isinstance(observed, dict):
            observed = {}
        runtime = cast(
            "dict[str, Any]",
            observed.get("runtime") if isinstance(observed.get("runtime"), dict) else {},
        )
        return {
            **declared,
            **{key: value for key, value in observed.items() if key in {
                "models", "tools", "skills", "permissions", "workspace", "memory", "collaboration", "features"
            }},
            "source_status": "observed",
            "runtime": {
                **declared["runtime"],
                **runtime,
                "framework": "agentscope",
                "framework_version": (
                    runtime.get("framework_version")
                    or observed.get("version")
                    or options.get("framework_version")
                ),
            },
        }
