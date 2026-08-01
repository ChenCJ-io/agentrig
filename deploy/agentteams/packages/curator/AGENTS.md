# Operating contract

Use only the `simulate-tool-result` Skill and the `agentrig-curator` MCP server.
Matrix carries a compact task envelope; retrieve complete input through MCP. Stop on
role mismatch, terminal state, contradictory schema, or expired deadline.
Include the exact `agentinv_...` task ID in the final stable completion or failure
message so AgentRig can correlate the Matrix receipt without guessing.
