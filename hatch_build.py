"""Conditionally package the production web client.

Editable installs must work from a clean checkout before Node dependencies are
installed. Release artifacts, however, must contain a freshly built SPA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Add ``web/dist/client`` only after the frontend has been built."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        client_dir = Path(self.root, "web", "dist", "client")
        if client_dir.is_dir():
            target = (
                "agentrig/web_dist"
                if self.target_name == "wheel"
                else "web/dist/client"
            )
            build_data["force_include"][str(client_dir)] = target
            return

        if self.target_name == "wheel" and version == "editable":
            return

        raise RuntimeError(
            "Production web client is missing. Run "
            "`cd web && npm ci && npm run build` before building a release artifact."
        )
