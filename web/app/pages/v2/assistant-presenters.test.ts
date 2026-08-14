import { describe, expect, it } from "vitest";

import {
  canonicalAssistantEvents,
  decisionActionLabel,
  decisionKindLabel,
  evidenceKindLabel,
  policyLabel,
  shortId,
  statusLabel,
  tone,
} from "./assistant-presenters";
import type { AssistantEvent } from "~/api/v2";

describe("assistant presenters", () => {
  it.each([
    ["succeeded", "success"],
    ["failed", "danger"],
    ["running", "accent"],
    ["pending", "warning"],
    ["unknown", "neutral"],
  ])("maps %s to badge tone %s", (value, expected) => {
    expect(tone(value)).toBe(expected);
  });

  it("uses Chinese labels with readable fallbacks", () => {
    expect(statusLabel("awaiting_confirmation")).toBe("等待确认");
    expect(statusLabel("custom_status")).toBe("custom status");
    expect(decisionKindLabel("execution_strategy")).toBe("执行策略");
    expect(decisionKindLabel("custom_kind")).toBe("custom_kind");
    expect(decisionActionLabel("submit_plan")).toBe("提交一个评测运行");
    expect(decisionActionLabel("custom_action")).toBe("custom action");
    expect(policyLabel("require_confirmation")).toBe("需要用户确认");
    expect(policyLabel("custom_policy")).toBe("custom_policy");
    expect(evidenceKindLabel("agent_invocation")).toBe("Worker 调用");
    expect(evidenceKindLabel("custom_evidence")).toBe("custom_evidence");
  });

  it("shortens only long resource identifiers", () => {
    expect(shortId("short_id")).toBe("short_id");
    expect(shortId("123456789012345678901234")).toBe("1234567890…01234");
  });

  it("keeps only the canonical Manager final reply for each turn", () => {
    const base = {
      session_id: "session",
      event_type: "assistant_message",
      actor_type: "manager",
      actor_id: "@manager:test",
      payload: {},
      plan_id: null,
      run_id: null,
      case_run_id: null,
      invocation_id: null,
      decision_id: null,
      matrix_event_id: null,
      delivery_status: "delivered",
      last_error: null,
      created_at: "2026-08-11T06:21:38",
    } satisfies Partial<AssistantEvent>;
    const events = [
      { ...base, id: "progress", seq: 1, turn_id: "turn" },
      { ...base, id: "unbound", seq: 2, turn_id: null },
      { ...base, id: "final", seq: 3, turn_id: "turn" },
      {
        ...base,
        id: "user",
        seq: 4,
        event_type: "user_message",
        actor_type: "user",
        turn_id: "next-turn",
      },
    ] as AssistantEvent[];

    expect(canonicalAssistantEvents(events).map((item) => item.id)).toEqual([
      "final",
      "user",
    ]);
  });
});
