"""Target 与版本列表的原子 CRUD。"""

from __future__ import annotations

from typing import Any

import httpx

from ..capabilities import (
    TargetCapabilitySnapshot,
    build_declared_snapshot,
    merge_observed_capabilities,
)
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..infrastructure.http_policy import TargetHttpPolicy
from ..infrastructure.secrets import SecretResolver
from .drivers import (
    DescribableAgentDriver,
    DriverPrepareContext,
    DriverRegistry,
)
from .options import merge_target_options
from .repository import TargetRepository
from .schemas import TargetCheck, TargetCreate, TargetPage, TargetPatch, TargetView


class TargetService:
    def __init__(
        self,
        repository: TargetRepository,
        *,
        drivers: DriverRegistry | None = None,
        secrets: SecretResolver | None = None,
        http_policy: TargetHttpPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._drivers = drivers
        self._secrets = secrets
        self._http_policy = http_policy or TargetHttpPolicy()

    async def create(self, value: TargetCreate) -> TargetView:
        target_id = value.id or new_id("target")
        if await self._repository.get(target_id) is not None:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                f"target already exists: {target_id}",
                details={"target_id": target_id},
            )
        self._validate_for_deployment(value)
        return await self._repository.create(target_id, value)

    async def get(self, target_id: str) -> TargetView:
        target = await self._repository.get(target_id)
        if target is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"target not found: {target_id}",
                details={"target_id": target_id},
            )
        return target

    async def list_targets(self, *, limit: int = 50, offset: int = 0) -> TargetPage:
        return await self._repository.list_page(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def update(self, target_id: str, patch: TargetPatch) -> TargetView:
        current = await self.get(target_id)
        data = current.model_dump(exclude={"id", "created_at", "updated_at"})
        merged = {**data, **patch.model_dump(exclude_unset=True), "id": target_id}
        value = TargetCreate.model_validate(merged)
        self._validate_for_deployment(value)
        return await self._repository.update(target_id, value)

    async def delete(self, target_id: str) -> None:
        await self.get(target_id)
        await self._repository.delete(target_id)

    def list_driver_types(self) -> list[dict[str, Any]]:
        if self._drivers is None:
            return []
        return self._drivers.descriptions()

    def schema(self, driver_type: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "target_schema": TargetCreate.model_json_schema(),
            "driver_type": driver_type,
            "options_schema": None,
            "options_example": None,
        }
        if driver_type is not None:
            if self._drivers is None:
                raise RuntimeError("TargetService Driver registry is not configured")
            result["options_schema"] = self._drivers.configuration_schema(driver_type)
            result["options_example"] = self._drivers.configuration_example(driver_type)
        return result

    async def check(
        self,
        target_id: str,
        *,
        version: str | None = None,
        timeout_seconds: float = 5,
    ) -> TargetCheck:
        target = await self.get(target_id)
        if self._drivers is None or self._secrets is None:
            raise RuntimeError("TargetService check dependencies are not configured")
        version_config = next(
            (item for item in target.versions if item.version == version),
            None,
        )
        endpoint = (
            version_config.endpoint
            if version_config is not None and version_config.endpoint is not None
            else target.endpoint
        )
        options = merge_target_options(
            target.options,
            version_config.options if version_config is not None else {},
        )
        try:
            capabilities = self._drivers.validate_configuration(
                target.driver_type,
                options=options,
                secret_configured=target.secret_ref is not None,
            )
            secret = self._secrets.resolve(target.secret_ref)
            probed = await self._drivers.probe(
                target.driver_type,
                DriverPrepareContext(
                    case_run_id=new_id("targetcheck"),
                    target={
                        "id": target.id,
                        "driver_type": target.driver_type,
                        "endpoint": endpoint,
                        "options": options,
                    },
                    version=version,
                    secret_value=secret,
                    component_timeout_seconds=timeout_seconds,
                ),
            )
        except Exception as exc:
            return TargetCheck(
                reachable=False,
                driver_type=target.driver_type,
                version=version,
                endpoint=endpoint,
                message=f"target configuration is unavailable: {exc}",
            )
        if endpoint and endpoint.startswith(("http://", "https://")):
            healthcheck_url = str(options.get("healthcheck_url") or endpoint)
            try:
                await self._http_policy.authorize_url(healthcheck_url)
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.get(healthcheck_url)
                message = f"HTTP endpoint responded with {response.status_code}"
                reachable = response.is_success
            except httpx.HTTPError as exc:
                message = f"HTTP endpoint is unreachable: {exc}"
                reachable = False
        else:
            message = (
                "driver process initialize/session probe succeeded"
                if probed
                else "driver configuration is valid; no network endpoint to probe"
            )
            reachable = True
        return TargetCheck(
            reachable=reachable,
            driver_type=target.driver_type,
            version=version,
            endpoint=endpoint,
            capabilities=capabilities.names(),
            message=message,
        )

    async def probe_capabilities(
        self,
        target_id: str,
        *,
        version: str | None = None,
        timeout_seconds: float = 5,
    ) -> TargetCapabilitySnapshot:
        """Observe current public capability metadata without mutating a CaseRun."""

        target = await self.get(target_id)
        if self._drivers is None or self._secrets is None:
            raise RuntimeError("TargetService probe dependencies are not configured")
        version_config = next(
            (item for item in target.versions if item.version == version),
            None,
        )
        if version is not None and version_config is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"target version not found: {version}",
                details={"target_id": target_id, "version": version},
            )
        endpoint = (
            version_config.endpoint
            if version_config is not None and version_config.endpoint is not None
            else target.endpoint
        )
        options = merge_target_options(
            target.options,
            version_config.options if version_config is not None else {},
        )
        if endpoint is not None:
            await self._http_policy.authorize_url(endpoint)
        capabilities = self._drivers.validate_configuration(
            target.driver_type,
            options=options,
            secret_configured=target.secret_ref is not None,
        )
        probe_id = new_id("targetprobe")
        snapshot_target = {
            "id": target.id,
            "name": target.name,
            "driver_type": target.driver_type,
            "version": version,
            "endpoint": endpoint,
            "options": options,
        }
        snapshot = build_declared_snapshot(
            case_run_id=probe_id,
            target=snapshot_target,
            profile={"tool_mode": "observe_only", "provider_chain": []},
            driver_capabilities=capabilities,
        )
        driver = self._drivers.create(
            target.driver_type,
            entrypoint=(str(options["entrypoint"]) if options.get("entrypoint") else None),
        )
        context = DriverPrepareContext(
            case_run_id=probe_id,
            target=snapshot_target,
            version=version,
            secret_value=self._secrets.resolve(target.secret_ref),
            component_timeout_seconds=timeout_seconds,
        )
        session = await driver.prepare(context)
        try:
            if isinstance(driver, DescribableAgentDriver):
                observed = await driver.describe_capabilities(context, session)
                snapshot = merge_observed_capabilities(snapshot, observed)
        finally:
            await driver.close(session)
        return snapshot

    async def authorize_execution(
        self,
        target: TargetView,
        *,
        version: str | None,
    ) -> None:
        version_configs = (
            target.versions
            if version is None
            else [item for item in target.versions if item.version == version]
        )
        endpoints = {
            item.endpoint if item.endpoint is not None else target.endpoint
            for item in version_configs
        }
        if not version_configs:
            endpoints.add(target.endpoint)
        for endpoint in endpoints:
            if endpoint is not None:
                await self._http_policy.authorize_url(endpoint)

    def _validate_for_deployment(self, value: TargetCreate) -> None:
        if self._drivers is None:
            return
        endpoint_and_options = (
            [
                (
                    version.endpoint if version.endpoint is not None else value.endpoint,
                    merge_target_options(value.options, version.options),
                )
                for version in value.versions
            ]
            if value.versions
            else [(value.endpoint, value.options)]
        )
        for endpoint, options in endpoint_and_options:
            try:
                if endpoint is not None:
                    self._http_policy.validate_url(endpoint)
                healthcheck_url = options.get("healthcheck_url")
                if healthcheck_url is not None:
                    self._http_policy.validate_url(str(healthcheck_url))
                self._drivers.validate_stored_configuration(
                    value.driver_type,
                    options=options,
                    secret_configured=value.secret_ref is not None,
                )
            except AgentRigError:
                raise
            except (TypeError, ValueError, PermissionError) as exc:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    f"invalid {value.driver_type} target configuration: {exc}",
                    details={"driver_type": value.driver_type},
                ) from exc
