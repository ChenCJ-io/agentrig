"""内置与本地 Python Driver 注册表。"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import cast

from ...errors import AgentRigError, ErrorCode
from .acp import AcpDriver
from .base import AgentDriver, DriverCapabilities
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
            "http_sse": HttpSseDriver,
            "pixcake_http_sse": PixcakeHttpSseDriver,
            "openai_compatible": OpenAICompatibleDriver,
        }
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
