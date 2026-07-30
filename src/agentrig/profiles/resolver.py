"""项目默认值、保存 Profile 和单次覆盖的确定性合并。"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from .schemas import ComponentTimeouts, ExecutionProfileConfig, ProfileView


class ProfileResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def defaults(self) -> ExecutionProfileConfig:
        return ExecutionProfileConfig(
            concurrency=self._settings.execution.default_concurrency,
            case_timeout_seconds=self._settings.execution.default_case_timeout_seconds,
            component_timeouts=ComponentTimeouts(
                driver=self._settings.execution.default_component_timeout_seconds,
                real_tool=self._settings.execution.default_component_timeout_seconds,
                curator=self._settings.execution.default_component_timeout_seconds,
                judge=self._settings.execution.default_component_timeout_seconds,
            ),
        )

    def resolve(
        self,
        profile: ProfileView | None,
        overrides: dict[str, Any],
        *,
        repeat_count: int | None,
    ) -> ExecutionProfileConfig:
        base = (
            profile.config.model_dump(mode="json")
            if profile is not None
            else self.defaults().model_dump(mode="json")
        )
        clean_overrides = {
            key: value
            for key, value in overrides.items()
            if value is not None
        }
        if "component_timeouts" in clean_overrides:
            clean_overrides["component_timeouts"] = {
                **base.get("component_timeouts", {}),
                **clean_overrides["component_timeouts"],
            }
        if repeat_count is not None:
            clean_overrides["repeat_count"] = repeat_count
        resolved = ExecutionProfileConfig.model_validate({**base, **clean_overrides})
        if resolved.concurrency > self._settings.execution.max_concurrency:
            resolved = resolved.model_copy(
                update={"concurrency": self._settings.execution.max_concurrency}
            )
        return resolved
