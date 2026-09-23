"""在被测 Agent 自己的 Python 解释器里运行 AgentRig harness 的 Driver。

harness（``agentrig.sdk.harness``）加载 Agno Agent/Team、LangGraph 编译图或普通函数，在
框架层接管工具调用，并复用 subprocess Driver 的 JSONL 协议。被测环境不需要安装
AgentRig：Driver 把只依赖标准库的 ``agentrig.sdk`` 复制到私有临时目录，通过 PYTHONPATH
提供给被测解释器，服务端依赖不会覆盖被测环境自己的依赖。
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..driver_schemas import PythonAgentTargetOptions
from .base import DriverCapabilities, DriverPrepareContext, DriverSession
from .subprocess import SubprocessDriver

HARNESS_MODULE = "agentrig.sdk.harness"
HARNESS_PROTOCOL = "agentrig.harness.v1"
_CONTROLLED = "controlled"
# 与 ACP Driver 一样只继承最小环境，另加被测 Agent 访问模型常用的语言、代理与证书变量。
_INHERITED_ENV = (
    "HOME",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "USER",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERNAME",
    "USERPROFILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
)

_bundle_lock = threading.Lock()
_bundle_root: Path | None = None


class PythonAgentDriver(SubprocessDriver):
    def capabilities(self) -> DriverCapabilities:
        return DriverCapabilities(
            multi_turn=True,
            tool_call_observation=True,
            tool_result_injection=True,
            usage_metrics=True,
        )

    def validate_configuration(
        self,
        options: dict[str, Any],
        *,
        secret_configured: bool,
    ) -> None:
        """静态检查启动配置，不启动解释器、不导入被测代码。"""

        parsed = PythonAgentTargetOptions.model_validate(options)
        if parsed.python not in self._allowlist:
            raise PermissionError(
                "python_agent interpreter is not permitted by deployment "
                f"subprocess_allowlist: {parsed.python}"
            )
        interpreter = Path(parsed.python)
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError(f"python_agent interpreter is not executable: {parsed.python}")
        if parsed.cwd is not None and not Path(parsed.cwd).is_dir():
            raise ValueError(f"python_agent cwd is not a directory: {parsed.cwd}")
        if parsed.credential_env is not None:
            _validate_env_name(parsed.credential_env, field="credential_env")
            if not secret_configured:
                raise ValueError("python_agent credential_env requires target secret_ref")
        elif secret_configured:
            raise ValueError("python_agent secret_ref requires options.credential_env")
        for name in parsed.env:
            _validate_env_name(name, field="env")
        for name in parsed.inherit_env:
            _validate_env_name(name, field="inherit_env")

    async def prepare(self, context: DriverPrepareContext) -> DriverSession:
        raw_options = dict(context.target.get("options") or {})
        self.validate_configuration(
            raw_options,
            secret_configured=context.secret_value is not None,
        )
        options = PythonAgentTargetOptions.model_validate(raw_options)
        command = [
            options.python,
            "-m",
            HARNESS_MODULE,
            "--entry",
            options.entry,
            "--adapter",
            options.adapter,
        ]
        if options.factory:
            command.append("--factory")
        session = await self._spawn(
            command,
            cwd=options.cwd,
            env=_harness_environment(options, secret_value=context.secret_value),
        )
        session.state.update(
            {
                "version": context.version,
                "initial_state": context.initial_state,
                "case_run_id": context.case_run_id,
                "tool_mode": context.tool_mode or _CONTROLLED,
                "startup_timeout": options.startup_timeout_seconds,
            }
        )
        return session

    async def probe(self, context: DriverPrepareContext) -> None:
        """真实启动 harness、导入被测 Agent 并完成一次 describe 握手。"""

        session = await self.prepare(context)
        try:
            await self._describe(session)
        finally:
            await self.close(session)

    async def describe_capabilities(
        self,
        context: DriverPrepareContext,
        session: DriverSession,
    ) -> dict[str, Any]:
        del context
        declared: dict[str, Any] = {
            "source_status": "declared",
            "runtime": {"protocol": "agentrig_harness", "protocol_version": "1"},
            "features": {
                key: {"status": "declared", "value": value}
                for key, value in self.capabilities().model_dump().items()
            },
        }
        try:
            description = await self._describe(session)
        except (OSError, RuntimeError, TimeoutError, ValueError):
            return declared
        runtime = description.get("runtime")
        tools = description.get("tools")
        return {
            **declared,
            "source_status": "observed",
            "runtime": {
                **(runtime if isinstance(runtime, dict) else {}),
                **declared["runtime"],
            },
            "tools": [item for item in tools if isinstance(item, dict)]
            if isinstance(tools, list)
            else [],
        }

    def _chat_payload(self, session: DriverSession, message: str) -> dict[str, Any]:
        return {
            "type": "chat",
            "message": message,
            "version": session.state.get("version"),
            "initial_state": session.state.get("initial_state"),
            "case_run_id": session.state.get("case_run_id"),
            "tool_mode": session.state.get("tool_mode"),
        }

    def _stops_at_tool_calls(self, session: DriverSession) -> bool:
        # 非受控模式下 harness 真实执行工具并继续输出，tool_calls 不再表示等待回灌。
        return str(session.state.get("tool_mode") or _CONTROLLED) == _CONTROLLED

    async def _describe(self, session: DriverSession) -> dict[str, Any]:
        timeout = float(session.state.get("startup_timeout") or 60)
        return await asyncio.wait_for(self._request_description(session), timeout=timeout)

    async def _request_description(self, session: DriverSession) -> dict[str, Any]:
        process: asyncio.subprocess.Process = session.state["process"]
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("python agent harness pipes are unavailable")
        process.stdin.write(b'{"type": "describe"}\n')
        await process.stdin.drain()
        raw = await process.stdout.readline()
        if not raw:
            raise RuntimeError(
                f"python agent harness exited unexpectedly: {await self._stderr_tail(session)}"
            )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("python agent harness returned an invalid description")
        if value.get("type") == "error":
            raise RuntimeError(str(value.get("error") or "python agent harness failed"))
        if value.get("type") != "description" or value.get("protocol") != HARNESS_PROTOCOL:
            raise ValueError("python agent harness speaks an unsupported protocol")
        return value


def _validate_env_name(value: str, *, field: str) -> None:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
        raise ValueError(
            f"python_agent {field} contains an invalid environment variable name: {value}"
        )


def _harness_environment(
    options: PythonAgentTargetOptions,
    *,
    secret_value: str | None,
) -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in (*_INHERITED_ENV, *options.inherit_env)
        if name in os.environ
    }
    environment.update(options.env)
    # 按被测解释器所在 venv 激活，被测代码里再启动的 python 也用同一个环境。
    interpreter_dir = Path(options.python).parent
    if (interpreter_dir.parent / "pyvenv.cfg").is_file():
        environment["VIRTUAL_ENV"] = str(interpreter_dir.parent)
        environment["PATH"] = os.pathsep.join(
            item for item in (str(interpreter_dir), environment.get("PATH")) if item
        )
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(sdk_bundle()), environment.get("PYTHONPATH")) if item
    )
    if options.credential_env and secret_value:
        environment[options.credential_env] = secret_value
    return environment


def sdk_bundle() -> Path:
    """返回只包含 ``agentrig.sdk`` 的私有目录，进程内复用，退出时删除。"""

    global _bundle_root
    with _bundle_lock:
        if _bundle_root is not None and (_bundle_root / "agentrig" / "sdk").is_dir():
            return _bundle_root
        package = Path(__file__).resolve().parents[2]
        root = Path(tempfile.mkdtemp(prefix="agentrig-harness-"))
        (root / "agentrig").mkdir()
        shutil.copy2(package / "__init__.py", root / "agentrig" / "__init__.py")
        shutil.copytree(
            package / "sdk",
            root / "agentrig" / "sdk",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        atexit.register(shutil.rmtree, root, True)
        _bundle_root = root
        return root
