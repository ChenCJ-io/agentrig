# AgentRig

English | [中文](./README.md)

> The MCP-native regression test rig for AI agents.

AgentRig V2 adds an intelligent evaluation assistant to the deterministic V1 core.
An AgentTeams Manager turns natural-language goals into previewable, confirmable, and
idempotently submitted EvaluationPlans. Simulation Curator and Evidence Judge run as
role-isolated Workers. AgentRig remains authoritative for execution, permissions,
evidence, and verdict records; AgentTeams owns multi-agent collaboration.

The two specialist agents can use either the V1 local adapters or AgentTeams Workers:

- **Simulation Curator** generates and validates context-aware tool results after
  fixtures and approved samples miss.
- **Evidence Judge** returns pass, fail, or inconclusive from a rubric and persisted
  evidence.

AgentTeams is disabled by default, preserving all V1 HTTP, MCP, Web, and CLI behavior.
Core mode needs no model API key. A controller may disable Evidence Judge and submit its
own verdict after inspecting a CaseRun.

## Implemented

- One asynchronous `run_cases` path for single cases, batches, versions, repetitions,
  and two-target A/B runs.
- Stdio ACP (official Python SDK), HTTP/SSE, Pixcake HTTP/SSE, OpenAI-compatible,
  allowlisted Python, and experimental JSONL subprocess drivers.
- Controlled, CaseRun-scoped MCP proxy, and observe-only tool modes.
- ACP targets can receive a CaseRun-scoped MCP proxy with isolated runtime data,
  sessions, logs, and workspaces.
- Configurable Fixture → Sample → Simulation Curator → Real Tool provider order.
- Separate Rule, Evidence Judge, and External Controller records.
- Async SQLAlchemy for SQLite/PostgreSQL, a 17-table schema, Alembic migrations, and
  immutable run snapshots.
- Durable assistant events, an EvaluationPlan state machine, AgentInvocation lifecycle,
  Matrix bridge, and reconnect-safe run notifications.
- Three AgentTeams role packages, isolated role MCP surfaces, HTTP/SSE APIs, a React UI,
  and eleven controller/collaboration skills.

## Quick start

Python 3.12+ and [uv](https://docs.astral.sh/uv/) are required. Building the Web UI also
requires Node.js 20+.

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

Persistent databases are no longer silently patched from ORM metadata. Startup checks
the Alembic revision and fails when the schema is uninitialized or stale; run
`uv run agentrig db upgrade` first. In-memory SQLite test databases are still created
automatically.

Default endpoints:

| Surface | URL |
|---|---|
| Web | `http://127.0.0.1:8000/` |
| HTTP API | `http://127.0.0.1:8000/api/` |
| V2 assistant API | `http://127.0.0.1:8000/api/v2/` |
| Controller MCP | `http://127.0.0.1:8000/mcp/` |
| Manager MCP | `http://127.0.0.1:8000/mcp/manager/` |
| Curator / Judge MCP | `http://127.0.0.1:8000/mcp/curator/`, `/mcp/judge/` |
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
# Configure only behind a trusted proxy that strips and rewrites this header.
# trusted_principal_header = "x-authenticated-user"

[execution]
default_concurrency = 4
max_concurrency = 20
max_repeat_count = 20
max_cases_per_run = 200
max_planned_case_runs = 1000

[target_network]
allow_private_networks = false
# Replace these local-development defaults with the exact trusted Target hosts in production.
allowed_hosts = ["localhost", "127.0.0.1", "::1"]

[reporting]
# Oversized reports fail explicitly instead of producing a silently truncated download.
max_report_case_runs = 10000
max_export_records = 10000
```

Target HTTP(S) URLs are checked when saved and before each run. Link-local, loopback,
private, and hostnames resolving to non-public addresses are rejected unless explicitly
trusted. In production, prefer exact `allowed_hosts` entries (or `*.example.com`) over
`allow_private_networks = true`.

Run reports and JSON/Markdown/HTML exports are generated server-side from every page and
pass through the evidence redactor. A changing dataset returns a retryable conflict, and
the `[reporting]` limits reject oversized output instead of truncating it.

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

The repository also includes a model-free, network-free
[Public Reference Target](./examples/reference_target/README.md) for reproducible success,
policy-regression, and explicit-recovery scenarios:

```bash
scripts/reference_demo.sh all --profile reference-ci
```

The command starts AgentRig and the public target, verifies success, A/B policy
regression, and explicit recovery, then exports a submission-oriented directory with an
`agentrig.release-evidence.v1` manifest, compact run evidence, a CycloneDX 1.6 SBOM,
public configuration, dependency-lock snapshots, and `SHA256SUMS`. From a clean checkout,
run the strict offline gate with:

```bash
scripts/reference_demo.sh validate-evidence --require-clean-source
```

See the Reference Target document for subcommands and artifact details.

See [docs](./docs/README.md) for architecture and module boundaries, and
[skills](./skills/README.md) for controller workflows. AgentTeams packaging and deployment
instructions live in [deploy/agentteams](./deploy/agentteams/README.md).

## Validation

```bash
uv run ruff check src tests scripts examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run build
```

## Status

The current version is `0.2.0a0`. V2 is implemented but remains Alpha. A live
AgentTeams/Matrix/cloud integration requires deployment-provided credentials and should
not yet be used as an unattended production release gate.

## License

MIT — see [LICENSE](./LICENSE).
