# AgentRig quick start and secure deployment

This guide covers the shortest reproducible path, a minimal local server, and the security controls required
for a shared deployment. The deeper architecture and acceptance records are currently maintained in Chinese;
the commands and configuration contracts below are language-independent.

## Choose a path

| Path | Best for | External dependencies |
|---|---|---|
| **Public Reference Demo** | First run, CI, protocol and evidence inspection | Python 3.12+, uv, Node.js 20+ |
| **Minimal local server** | API, MCP, and Web development | Python 3.12+, uv, Node.js 20+ |
| **Complete AgentTeams demo** | Live roles, Matrix, and real-target acceptance | Docker, lassist, deployment credentials |

## Public Reference Demo

The reference path runs fixed success, policy-regression, and explicit-recovery scenarios. Dependency
installation needs package-registry access; scenario execution itself uses no model, private repository, or
external service.

```bash
git clone https://github.com/ChenCJ-io/agentrig.git
cd agentrig
scripts/reference_demo.sh all --profile reference-ci
```

Open AgentRig at `http://127.0.0.1:8020`. The deterministic target runs at
`http://127.0.0.1:8091`, and exported artifacts are under `.agentrig/reference-demo/evidence/`.

```bash
scripts/reference_demo.sh validate-evidence --require-clean-source
scripts/reference_demo.sh status
scripts/reference_demo.sh down
```

Strict validation checks the Git SHA, exact versions, SBOM, public configuration, artifact hashes, and
Run/CaseRun references without network access. The policy-regression scenario also exports
`quality-report.json`, `comparison-report.json`, and an expected-failing `release-gate.json` from the same
source snapshot, proving that the gate blocks the known regression.

## Minimal local server

```bash
uv sync --extra dev
cd web && npm ci && npm run build && cd ..
uv run agentrig db upgrade
uv run agentrig serve
```

| Surface | Default URL |
|---|---|
| Web | `http://127.0.0.1:8000/` |
| HTTP API | `http://127.0.0.1:8000/api/` |
| Assistant API | `http://127.0.0.1:8000/api/v2/` |
| Controller MCP | `http://127.0.0.1:8000/mcp/` |
| Manager MCP | `http://127.0.0.1:8000/mcp/manager/` |
| Curator / Judge MCP | `http://127.0.0.1:8000/mcp/curator/`, `/mcp/judge/` |
| Tested-agent tool proxy | `http://127.0.0.1:8000/proxy` |

Run the built-in vertical acceptance without an external target:

```bash
uv run agentrig demo
```

## Minimal configuration

```toml
[server]
host = "127.0.0.1"
port = 8000

[database]
url = "sqlite+aiosqlite:///./.agentrig/agentrig.db"

[proxy]
public_url = "http://127.0.0.1:8000/proxy"
backends = { business = "http://127.0.0.1:9001/mcp/" }

[execution]
real_tool_allowlist = []
python_driver_allowlist = []
subprocess_allowlist = []
durable_scheduler_enabled = false

[target_network]
allow_private_networks = false
allowed_hosts = ["localhost", "127.0.0.1", "::1"]

[run_otlp_export]
enabled = false
endpoint = ""

[production_evidence]
enabled = false
```

Persistent databases require an Alembic migration before startup:

```bash
uv run agentrig db upgrade
```

Execution profiles may embed an immutable `agentrig.pricing-snapshot.v1`. Cost is calculated only when the
event model and required token/cache fields match that frozen snapshot; otherwise reports keep cost `null`
and explain the limitation. Terminal Run OTLP export is best-effort and metadata-only. Production OTLP
ingest remains disabled by default and requires a Project, an enabled Ingest Source, and its dedicated token.

## Authentication and secrets

Shared or public deployments must use a Bearer token. Store only an environment-variable reference in
configuration:

```toml
[server]
api_token_ref = "env:AGENTRIG_ACCESS_TOKEN"
```

```bash
export AGENTRIG_ACCESS_TOKEN='replace-with-a-random-token'
```

Codex MCP configuration also references the environment variable rather than the token value:

```toml
[mcp_servers.agentrig]
url = "http://127.0.0.1:8000/mcp/"
bearer_token_env_var = "AGENTRIG_ACCESS_TOKEN"
```

Target and model credentials accept `env:VARIABLE_NAME` references. Never place real values in project
configuration, target definitions, Skills, screenshots, or logs.

## Security boundaries

- Target URLs are checked on save and before every run against URL, DNS, private-network, and host policies.
- Keep `allow_private_networks = false`; list exact trusted hosts instead of disabling egress protection.
- Real tools require deployment allowlisting, an enabled profile provider, and user authorization.
- Python and subprocess drivers must be installed and allowlisted by the deployer; MCP cannot upload code.
- Manager, Curator, and Judge use separate MCP permissions and credentials.
- Reports fail explicitly at configured limits rather than silently truncating evidence.
- A trusted principal header is valid only behind a proxy that strips and rewrites the client header.

Containers that must reach the host proxy should use `host.docker.internal` (or the platform equivalent) and
must enable the service Bearer token; a loopback URL is not container-reachable.

## Complete AgentTeams acceptance

The complete path connects AgentRig, AgentTeams v1.1.2, Matrix, three isolated roles, and a real
lassist/Pixcake target. Follow the [local acceptance guide](./04-本机演示与验收.md), keep credentials in
ignored local files, then run:

```bash
scripts/local_demo.sh all
scripts/local_demo.sh verify
```

Reference CI is deterministic evidence for the Core path; it must not be presented as live AgentTeams proof.

## V2.3—V2.5 acceptance

Run all deterministic contracts, migrations, Python/Web checks, and the real
Browser→FastAPI→SQLite→Reference Target path with:

```bash
scripts/accept_v23.sh local
```

The version-pinned AgentScope 2.0.6, AgentTeams v1.1.2/v1.2.2, and PostgreSQL checks require controlled
external environments. See the [acceptance runbook](./09-V2.3-Agent运行时验证与生产证据闭环/11-验收运行手册.md)
and run `scripts/accept_v23.sh live`; an unexecuted live check is not a pass.

## Validation

```bash
uv run ruff check src tests scripts examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run test:coverage && npm run e2e && npm run build
```

For support, see [SUPPORT.md](../SUPPORT.md). Report vulnerabilities privately according to
[SECURITY.md](../SECURITY.md).
