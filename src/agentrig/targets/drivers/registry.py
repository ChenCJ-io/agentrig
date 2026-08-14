"""内置与本地 Python Driver 注册表。"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, cast

from ...errors import AgentRigError, ErrorCode
from ..driver_schemas import options_example, options_schema
from .acp import AcpDriver
from .ag_ui import AgUiDriver
from .agentscope import AgentScopeDriver
from .base import (
    AgentDriver,
    ConfigurableAgentDriver,
    DriverCapabilities,
    DriverPrepareContext,
    ProbeableAgentDriver,
)
from .http_sse import HttpSseDriver
from .openai_compatible import OpenAICompatibleDriver
from .pixcake_http_sse import PixcakeHttpSseDriver
from .subprocess import SubprocessDriver

DriverFactory = Callable[[], AgentDriver]


class DriverRegistry:
    def __init__(
        self,
        *,
        python_allowlist: list[str] | None = None,
        subprocess_allowlist: list[str] | None = None,
    ) -> None:
        self._factories: dict[str, DriverFactory] = {
            "acp": lambda: AcpDriver(
                executable_allowlist=self._subprocess_allowlist
            ),
            "ag_ui": AgUiDriver,
            "agentscope": AgentScopeDriver,
            "http_sse": HttpSseDriver,
            "pixcake_http_sse": PixcakeHttpSseDriver,
            "openai_compatible": OpenAICompatibleDriver,
        }
        self._builtin_driver_types = set(self._factories)
        self._subprocess_allowlist = list(subprocess_allowlist or [])
        self._python_allowlist = set(python_allowlist or [])

    def register(self, driver_type: str, factory: DriverFactory) -> None:
        self._factories[driver_type] = factory

    def create(self, driver_type: str, *, entrypoint: str | None = None) -> AgentDriver:
        if driver_type == "subprocess":
            return SubprocessDriver(executable_allowlist=self._subprocess_allowlist)
        if driver_type == "python":
            if not entrypoint or entrypoint not in self._python_allowlist:
                raise AgentRigError(
                    ErrorCode.PERMISSION_DENIED,
                    "python driver entrypoint is not in the deployment allowlist",
                    details={"entrypoint": entrypoint},
                )
            module_name, separator, attribute = entrypoint.partition(":")
            if not separator:
                raise AgentRigError(
                    ErrorCode.VALIDATION_ERROR,
                    "python driver entrypoint must use module:Class",
                )
            module = importlib.import_module(module_name)
            loaded_factory = cast(DriverFactory, getattr(module, attribute))
            return loaded_factory()
        registered_factory = self._factories.get(driver_type)
        if registered_factory is None:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                f"unsupported driver type: {driver_type}",
                details={"driver_type": driver_type},
            )
        return registered_factory()

    def capabilities(
        self,
        driver_type: str,
        *,
        entrypoint: str | None = None,
    ) -> DriverCapabilities:
        return self.create(driver_type, entrypoint=entrypoint).capabilities()

    def validate_configuration(
        self,
        driver_type: str,
        *,
        options: dict[str, Any],
        secret_configured: bool,
    ) -> DriverCapabilities:
        """校验当前部署能否使用这份 Driver 配置。"""

        driver = self.create(
            driver_type,
            entrypoint=(
                str(options["entrypoint"])
                if options.get("entrypoint") is not None
                else None
            ),
        )
        if isinstance(driver, ConfigurableAgentDriver):
            driver.validate_configuration(
                options,
                secret_configured=secret_configured,
            )
        return driver.capabilities()

    def validate_stored_configuration(
        self,
        driver_type: str,
        *,
        options: dict[str, Any],
        secret_configured: bool,
    ) -> None:
        """写入前检查类型和静态配置，不实例化可能有副作用的自定义 Driver。"""

        if driver_type == "acp":
            AcpDriver(
                executable_allowlist=self._subprocess_allowlist
            ).validate_configuration(
                options,
                secret_configured=secret_configured,
            )
            return
        if driver_type == "subprocess":
            return
        if driver_type == "python":
            entrypoint = options.get("entrypoint")
            if not isinstance(entrypoint, str) or entrypoint not in self._python_allowlist:
                raise AgentRigError(
                    ErrorCode.PERMISSION_DENIED,
                    "python driver entrypoint is not in the deployment allowlist",
                    details={"entrypoint": entrypoint},
                )
            return
        if driver_type not in self._factories:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                f"unsupported driver type: {driver_type}",
                details={"driver_type": driver_type},
            )

    async def probe(self, driver_type: str, context: DriverPrepareContext) -> bool:
        """若 Driver 支持真实探针则执行，返回是否执行过。"""

        options = dict(context.target.get("options") or {})
        driver = self.create(
            driver_type,
            entrypoint=(
                str(options["entrypoint"])
                if options.get("entrypoint") is not None
                else None
            ),
        )
        if not isinstance(driver, ProbeableAgentDriver):
            return False
        await driver.probe(context)
        return True

    def descriptions(self) -> list[dict[str, Any]]:
        """列出当前部署可识别的 Driver，不暴露 allowlist 具体内容。"""

        descriptions: list[dict[str, Any]] = []
        for driver_type, factory in sorted(self._factories.items()):
            capabilities = (
                factory().capabilities().names()
                if driver_type in self._builtin_driver_types
                else []
            )
            descriptions.append(
                {
                    "driver_type": driver_type,
                    "capabilities": capabilities,
                    "options_schema_available": options_schema(driver_type)
                    is not None,
                    "deployment_ready": (
                        bool(self._subprocess_allowlist)
                        if driver_type == "acp"
                        else True
                    ),
                }
            )
        descriptions.append(
            {
                "driver_type": "subprocess",
                "capabilities": SubprocessDriver(
                    executable_allowlist=self._subprocess_allowlist
                ).capabilities().names(),
                "options_schema_available": False,
                "deployment_ready": bool(self._subprocess_allowlist),
            }
        )
        descriptions.append(
            {
                "driver_type": "python",
                "capabilities": [],
                "options_schema_available": False,
                "deployment_ready": bool(self._python_allowlist),
            }
        )
        return descriptions

    def configuration_schema(self, driver_type: str) -> dict[str, Any] | None:
        """返回 Driver options Schema；未知 Driver 仍按配置错误处理。"""

        if driver_type not in {*self._factories, "subprocess", "python"}:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                f"unsupported driver type: {driver_type}",
                details={"driver_type": driver_type},
            )
        return options_schema(driver_type)

    def configuration_example(self, driver_type: str) -> dict[str, Any] | None:
        self.configuration_schema(driver_type)
        return options_example(driver_type)
