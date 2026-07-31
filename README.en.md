# AgentRig

English | [中文](./README.md)

> The MCP-native regression test rig for AI agents.

AgentRig V1 is controlled by Codex, Claude Code, or a human operator. The controller
uses atomic MCP tools to select or author cases, submit asynchronous runs, inspect
redacted evidence, and optionally write an external verdict. AgentRig owns deterministic
execution, tool-result control, evidence persistence, and evaluator archives.

V1 includes two optional intelligent agents:

- **Simulation Curator** generates and validates context-aware tool results after
  fixtures and approved samples miss.
- **Evidence Judge** returns pass, fail, or inconclusive from a rubric and persisted
  evidence.

Core mode needs no model API key. A controller may disable Evidence Judge and submit its
own verdict after inspecting a CaseRun.

## Implemented in V1

- One asynchronous `run_cases` path for single cases, batches, versions, repetitions,
  and two-target A/B runs.
- Stdio ACP (official Python SDK), HTTP/SSE, Pixcake HTTP/SSE, OpenAI-compatible,
  allowlisted Python, and experimental JSONL subprocess drivers.
- Controlled, CaseRun-scoped MCP proxy, and observe-only tool modes.
- ACP targets can receive a CaseRun-scoped MCP proxy with isolated runtime data,
  sessions, logs, and workspaces.
- Configurable Fixture → Sample → Simulation Curator → Real Tool provider order.
- Separate Rule, Evidence Judge, and External Controller records.
- Async SQLAlchemy for SQLite/PostgreSQL, an 11-table schema, Alembic migrations, and
  immutable run snapshots.
- HTTP API, Streamable HTTP MCP, a React administration UI, and Codex/Claude Code skills.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required. Building the Web UI also
requires Node.js 20+.

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

Default endpoints:

| Surface | URL |
|---|---|
| Web | `http://127.0.0.1:8000/` |
| HTTP API | `http://127.0.0.1:8000/api/` |
| Controller MCP | `http://127.0.0.1:8000/mcp/` |
| Tested-agent tool proxy | `http://127.0.0.1:8000/proxy` |

Codex MCP configuration:

```toml
[mcp_servers.agentrig]
url = "http://127.0.0.1:8000/mcp/"
# Uncomment when server.api_token_ref is enabled. Codex reads the token from the environment.
# bearer_token_env_var = "AGENTRIG_ACCESS_TOKEN"
```

A local ACP launcher must first be included in the deployment
`subprocess_allowlist`. Coding agents can call `list_driver_types` to check deployment
readiness and `get_target_schema(driver_type="acp")` for the complete options schema and
a secret-free example. `check_target` validates command, cwd, allowlist, Secret
references, and isolation settings, then performs an ACP initialize/session probe without
sending a prompt.

For a shared deployment, keep the access token in an environment variable and configure only
its reference:

```toml
[server]
api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"
```

The Web UI opens an access-token dialog after its first 401 response; the same dialog is
available from the user menu. The token is stored only in that browser's local storage.
Codex must inherit the same environment variable and set `bearer_token_env_var` in its
MCP configuration.

An ACP agent running in a container needs a host-reachable proxy URL. In that setup,
enable the access token instead of exposing an unauthenticated service:

```toml
[server]
host = "0.0.0.0"
port = 8000
api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"

[proxy]
public_url = "http://host.docker.internal:8000/proxy"
```

AgentRig injects both the server token and the short-lived CaseRun scope into the ACP MCP
configuration. Never put the token value in `agentrig.toml`, a Target, or Codex config.

Run the dependency-free vertical demo with:

```bash
uv run agentrig demo
```

See [docs](./docs/README.md) for architecture and module boundaries, and
[skills](./skills/README.md) for controller workflows.

## Validation

```bash
uv run ruff check src tests examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run build
```

## Status

The current version is `0.1.0a1`. The V1 core is implemented but remains Alpha and
should not yet be used as an unattended production release gate.

## License

MIT — see [LICENSE](./LICENSE).
