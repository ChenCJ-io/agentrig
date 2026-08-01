# AgentRig × AgentTeams deployment

This directory is the executable integration overlay; AgentTeams itself remains an
external dependency. The competition baseline is locked by [`VERSION`](./VERSION) to
`v1.1.2`. That tag still exposes legacy `hiclaw.io/v1beta1` resource names, so those
names are intentionally confined to [`resources-v1.1.2.yaml`](./resources-v1.1.2.yaml).

The official repository documents the stable installer, Manager/Worker architecture,
Matrix, Higress, MinIO, and declarative `Manager`/`Worker` resources:
https://github.com/agentscope-ai/AgentTeams/tree/v1.1.2

## 1. Build the three packages

```bash
uv run python scripts/build_agentteams_packages.py
unzip -l deploy/agentteams/dist/agentrig-manager.zip
unzip -l deploy/agentteams/dist/agentrig-curator.zip
unzip -l deploy/agentteams/dist/agentrig-judge.zip
```

The builder copies the current repository Skills, SOUL, and AGENTS contracts. It omits
Codex-only `agents/openai.yaml` metadata and emits deterministic archives.

## 2. Install the pinned external runtime

For the Docker/embedded profile, run the official installer with the version lock:

```bash
HICLAW_VERSION=v1.1.2 bash <(curl -sSL https://higress.ai/hiclaw/install.sh)
```

For Kubernetes, use the v1.1.2 chart (`helm/hiclaw` in that tag). Do not silently use
the current prerelease chart in a competition build. Keep Tuwunel, controller, MinIO,
and the Higress console private; expose only the authenticated Higress entry point.

## 3. Configure gateway routes and identities

Create three Higress MCP routes and restrict each to its matching consumer:

| Gateway route | Upstream | Allowed identity | Upstream Authorization |
|---|---|---|---|
| `agentrig-manager` | `http://agentrig:8000/mcp/manager/` | Manager | `AGENTRIG_MANAGER_MCP_TOKEN` |
| `agentrig-curator` | `http://agentrig:8000/mcp/curator/` | Curator | `AGENTRIG_CURATOR_MCP_TOKEN` |
| `agentrig-judge` | `http://agentrig:8000/mcp/judge/` | Judge | `AGENTRIG_JUDGE_MCP_TOKEN` |

Workers hold only their Higress consumer keys. Higress injects the separate AgentRig
upstream token; never place AgentRig or model secrets in a Skill, Matrix message, CR,
or package.

Create a Matrix service user for `agentrig-bridge`, obtain its access token, and record
the exact Manager/Curator/Judge Matrix user IDs. Also create one private fallback Worker
room for V1 Core runs that have no AssistantSession and set `default_worker_room_id`.
Invite only the bridge, Curator, and Judge identities to that room. Copy
[`agentrig.competition.toml.example`](./agentrig.competition.toml.example) to the runtime
configuration and replace domains/URLs. Export real secrets based on
[`environment.example`](./environment.example) from a secret manager.

## 4. Apply Agent resources

Copy the built archives and YAML into the AgentTeams Manager working directory, then:

```bash
hiclaw apply -f resources-v1.1.2.yaml
```

The official CLI processes multi-document YAML in order. This overlay declares one
Manager and two standalone Workers. AgentRig creates one private Matrix room per Web
assistant session and invites those identities.

## 5. Start and verify AgentRig

```bash
uv run agentrig db upgrade
uv run agentrig serve
curl -fsS http://127.0.0.1:8000/api/v2/agentteams/health
```

Verify all of the following before a demo:

- `/mcp/manager/`, `/mcp/curator/`, and `/mcp/judge/` reject the wrong token;
- Manager tools do not include `run_cases`;
- Curator and Judge each expose exactly three role tools;
- creating a Web session produces a Matrix room;
- a user message is visible to Manager and a final Manager message projects back;
- Curator/Judge invocations show Matrix event IDs and reach a terminal state;
- disabling AgentTeams still leaves V1 `/api`, `/mcp/`, Rule runs, and stored evidence usable.

Install the official `alibabacloud-sls-query` Skill separately in the competition
environment and pin its source revision. Do not copy or rename it as an AgentRig Skill.
