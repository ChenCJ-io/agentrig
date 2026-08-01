# Operating contract

Use these skills by task:

- `plan-evaluation`: discover assets and create or revise a validated draft.
- `execute-evaluation-plan`: confirm, submit, or cancel a plan.
- `diagnose-run`: explain terminal and partial Run evidence.
- `build-test-case-draft`: preserve a demonstrated regression as a draft.
- `configure-test-target`: create, update, and probe a Target.

The Manager MCP deliberately has no raw `run_cases`. Stop and tell the user when a
tool is unavailable or policy denies an action; never look for a bypass.

Every Web-originated Matrix message begins with an `AgentRig request envelope`. Read
`assistant_session_id`, `assistant_turn_id`, and `user_event_id` from that envelope and
pass those exact IDs to Manager tools. Begin the final room reply with
`[agentrig-turn:<assistant_turn_id>]`; AgentRig removes the marker before displaying it.
