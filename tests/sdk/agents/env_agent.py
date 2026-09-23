"""回显被测进程可见的环境变量，验证 AgentRig 自身的 Secret 不会泄漏给被测代码。"""

from __future__ import annotations

import json
import os
from typing import Any

NAMES = ("HOST_SECRET", "FORWARDED_VAR", "EXPLICIT_VAR", "MODEL_KEY")


def run(messages: list[dict[str, Any]]) -> str:
    return json.dumps({name: os.environ.get(name) for name in NAMES})
