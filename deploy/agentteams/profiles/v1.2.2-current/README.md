# AgentTeams v1.2.2 current profile

This profile pins AgentTeams `v1.2.2` (`849182af8e017168a5a200a87b1062142caf462d`),
the `agentteams.io/v1beta1` API, and QwenPaw. It never falls back to the legacy API.

Before applying `resources.yaml`:

1. install the CRDs from the pinned upstream tag;
2. build deterministic AgentRig role packages;
3. verify the pinned multi-architecture OCI index digests in `manifest.json` against the registry;
4. validate resources against `resource-schema.json`;
5. use separate namespace, storage, credentials, and Matrix rooms from the competition profile.

The file contains no credentials. MCP endpoints are route identities only and should be secured by
the deployment gateway. A release is accepted only when observed Skill hashes, room membership,
and invocation canaries are present in `agentrig.agentteams-compat-report.v1`.
