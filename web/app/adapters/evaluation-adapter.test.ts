import { describe, expect, it } from "vitest";

import { toEvaluationCell, toRunListItem, toUiStatus } from "./evaluation-adapter";

describe("evaluation adapter", () => {
  it("keeps completed runs with failed attempts partial", () => {
    const result = toRunListItem({
      id: "run_12345678901234567890",
      status: "completed",
      resolved_case_ids: ["case_1"],
      target_snapshots: [{ id: "target_1", version: "v2" }],
      manifest_schema_version: "agentrig.run-manifest.v1",
      manifest_hash: "sha256:abc",
      manifest: null,
      recovery_of_run_id: null,
      recovery_reason: null,
      cell_count: 1,
      attempt_count: 2,
      finished_attempt_count: 2,
      total_count: 2,
      completed_count: 1,
      failed_count: 1,
      skipped_count: 0,
      cancelled_count: 0,
      created_at: "2026-08-11T10:00:00Z",
      finished_at: "2026-08-11T10:01:00Z",
    });
    expect(result.status).toBe("partial");
    expect(result.progress).toEqual({ completed: 2, total: 2, percent: 100 });
  });

  it("maps unknown states without inventing success", () => {
    expect(toUiStatus("something_new")).toBe("unknown");
  });

  it("maps the server timeline and keeps evidence references", () => {
    const cell = toEvaluationCell({
      cell_id: "cell_1",
      cell_key: "cell_1",
      run_id: "run_1",
      case_id: "case_1",
      target_id: "target_1",
      target_role: "candidate",
      version: "v1",
      status: "completed",
      evaluation_state: "pass",
      failure_class: null,
      attempt_count: 1,
      finished_attempt_count: 1,
      attempts: [],
      timeline: [{
        id: "timeline:event:evt_1",
        cell_id: "cell_1",
        attempt_id: "attempt_1",
        case_run_id: "cr_1",
        attempt_index: 1,
        source_type: "event",
        source_id: "evt_1",
        category: "tool_call",
        actor: "被测 Agent",
        status: "completed",
        title: "调用工具",
        summary: null,
        evidence_refs: ["evt_1"],
        payload: { tool: "search" },
        occurred_at: "2026-08-11T10:00:00Z",
      }],
    });
    expect(cell.timeline[0]?.kind).toBe("tool_call");
    expect(cell.timeline[0]?.evidenceRefs).toEqual(["evt_1"]);
  });
});
