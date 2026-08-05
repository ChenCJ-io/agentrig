import { describe, expect, it } from "vitest";

import type { DecisionRecord, EvidenceRef } from "~/api/v2";

import { evidenceNeedsTarget, evidenceSourcePath } from "./evidence-links";

const target = evidence("target", "target_lassist_local");
const run = evidence("run", "run_demo");

describe("evidenceSourcePath", () => {
  it.each([
    [evidence("target", "target_lassist_local"), "/targets/target_lassist_local/overview"],
    [evidence("target_check", "target_lassist_local"), "/targets/target_lassist_local/overview"],
    [evidence("test_case", "case_demo"), "/targets/target_lassist_local/evaluation/test-cases?case_id=case_demo"],
    [evidence("execution_profile", "profile_demo"), "/targets/target_lassist_local/assets/profiles?profile_id=profile_demo"],
    [evidence("tool_sample", "sample_demo"), "/targets/target_lassist_local/assets/tool-results?sample_id=sample_demo"],
    [run, "/targets/target_lassist_local/evaluation/runs/run_demo"],
    [evidence("assistant_event", "evt_demo"), "/targets/target_lassist_local/assistant#assistant-event-evt_demo"],
    [evidence("evaluation_plan", "plan_demo"), "/targets/target_lassist_local/assistant#evaluation-plan"],
    [evidence("agent_invocation", "inv_demo"), "/evaluator-teams?invocation_id=inv_demo"],
    [evidence("runtime_health", "health_demo"), "/evaluator-teams"],
  ])("maps %o to its source page", (ref, expected) => {
    expect(evidenceSourcePath(ref, decision([target, run]), "/targets/target_lassist_local/assistant")).toBe(expected);
  });

  it.each(["case_run", "run_event", "evaluation"])("anchors %s evidence in its run", (kind) => {
    expect(
      evidenceSourcePath(
        evidence(kind, `${kind}_demo`),
        decision([target, run]),
        "/targets/target_lassist_local/assistant",
      ),
    ).toBe(
      `/targets/target_lassist_local/evaluation/runs/run_demo?evidence_kind=${kind}&evidence_id=${kind}_demo#evidence-workbench`,
    );
  });

  it("derives a target from the selected action outside a target workspace", () => {
    const value = decision([]);
    value.selected_action.parameters.target_id = "target_from_action";
    expect(evidenceSourcePath(evidence("test_case", "case_demo"), value, "/assistant")).toBe(
      "/targets/target_from_action/evaluation/test-cases?case_id=case_demo",
    );
  });

  it("derives a target from target evidence outside a target workspace", () => {
    expect(evidenceSourcePath(evidence("run", "run_demo"), decision([target]), "/assistant")).toBe(
      "/targets/target_lassist_local/evaluation/runs/run_demo",
    );
  });

  it.each([
    ["execution_profile", "profile_demo"],
    ["tool_sample", "sample_demo"],
    ["run", "run_demo"],
  ])("uses the audit trail for %s without target context", (kind, resourceId) => {
    expect(evidenceSourcePath(evidence(kind, resourceId), decision([]), "/assistant")).toBe(
      `/audit?resource_kind=${kind}&resource_id=${resourceId}`,
    );
  });

  it("opens observability when granular run evidence has no run reference", () => {
    expect(
      evidenceSourcePath(evidence("case_run", "case_run_demo"), decision([target]), "/assistant"),
    ).toBe(
      "/targets/target_lassist_local/observability?evidence_kind=case_run&evidence_id=case_run_demo",
    );
    expect(
      evidenceSourcePath(evidence("case_run", "case_run_demo"), decision([]), "/assistant"),
    ).toBe("/audit?resource_kind=case_run&resource_id=case_run_demo");
  });

  it("falls back to the audit trail when a target cannot be resolved", () => {
    expect(evidenceSourcePath(evidence("test_case", "case a"), decision([]), "/assistant")).toBe(
      "/audit?resource_kind=test_case&resource_id=case+a",
    );
    expect(evidenceSourcePath(evidence("custom_fact", "fact/demo"), decision([]), "/assistant")).toBe(
      "/audit?resource_kind=custom_fact&resource_id=fact%2Fdemo",
    );
  });

  it("classifies evidence that needs target context", () => {
    for (const kind of ["case_run", "evaluation", "execution_profile", "run", "run_event", "test_case", "tool_sample"]) {
      expect(evidenceNeedsTarget(kind)).toBe(true);
    }
    expect(evidenceNeedsTarget("runtime_health")).toBe(false);
  });
});

function evidence(kind: string, resourceId: string): EvidenceRef {
  return { kind, resource_id: resourceId, version: null, snapshot_hash: null, label: null };
}

function decision(evidenceRefs: EvidenceRef[]): DecisionRecord {
  return {
    id: "dec_demo",
    session_id: "session_demo",
    turn_id: "turn_demo",
    parent_decision_id: null,
    ordinal: 1,
    schema_version: "1",
    trigger: "user_message",
    decision_kind: "plan",
    status: "succeeded",
    objective: "test",
    observation_summary: { known: [], unknown: [], constraints: [] },
    options: [],
    selected_action: { action_type: "create_plan", parameters: {} },
    rationale_summary: { summary: "test", tradeoffs: [] },
    evidence_refs: evidenceRefs,
    confidence: 0.9,
    context_hash: "hash",
    policy_verdict: { verdict: "allow", reasons: [], rule_version: "test" },
    confirmation_event_id: null,
    action_idempotency_key: null,
    action_ref_type: null,
    action_ref_id: null,
    error_code: null,
    error_message: null,
    proposed_by: "manager",
    created_at: "2026-08-05T00:00:00Z",
    authorized_at: null,
    started_at: null,
    finished_at: null,
  };
}
