import { describe, expect, it } from "vitest";

import {
  decisionActionLabel,
  decisionKindLabel,
  evidenceKindLabel,
  policyLabel,
  shortId,
  statusLabel,
  tone,
} from "./assistant-presenters";

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
});
