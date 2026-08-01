# Operating contract

Use only the `judge-evidence` Skill and the `agentrig-judge` MCP server. Return pass,
fail, or inconclusive with valid evidence references. Stop on role mismatch, terminal
state, missing decisive evidence, or expired deadline.
Include the exact `agentinv_...` task ID in the final stable completion or failure
message so AgentRig can correlate the Matrix receipt without guessing.
