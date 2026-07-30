"""V1 的 env-only Secret Resolver。"""

from __future__ import annotations

import os
import re

from ..errors import AgentRigError, ErrorCode

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecretResolver:
    def resolve(self, reference: str | None) -> str | None:
        if reference is None:
            return None
        if not reference.startswith("env:"):
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "only env: secret references are supported",
            )
        name = reference.removeprefix("env:")
        if not _ENV_NAME.fullmatch(name):
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                "invalid environment variable name in secret_ref",
                details={"secret_ref": reference},
            )
        value = os.environ.get(name)
        if value is None:
            raise AgentRigError(
                ErrorCode.VALIDATION_ERROR,
                f"secret environment variable is not set: {name}",
                details={"secret_ref": reference},
            )
        return value
