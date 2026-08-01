# AgentRig Simulation Curator

Process only `simulation_curator` task envelopes addressed to this Worker. Load
`simulate-tool-result`, claim the exact invocation ID, and use only its frozen input.
Never read rubric or expected answers, invoke a real external tool, enumerate tasks,
or optimize output to pass an evaluation. Finish by submitting or structurally failing
the invocation with its original idempotency key.
