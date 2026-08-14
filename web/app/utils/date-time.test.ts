import { describe, expect, it } from "vitest";

import {
  formatChinaDateTime,
  formatChinaEventTime,
  parseApiDateTime,
} from "./date-time";

describe("China timezone formatting", () => {
  it("treats timezone-naive API timestamps as UTC", () => {
    expect(formatChinaEventTime("2026-08-11T06:21:38.043411")).toBe("14:21:38");
    expect(formatChinaDateTime("2026-08-11T06:21:38.043411")).toBe(
      "2026-08-11 14:21:38",
    );
  });

  it("preserves timestamps that already carry an offset", () => {
    expect(formatChinaEventTime("2026-08-11T06:21:38Z")).toBe("14:21:38");
    expect(formatChinaEventTime("2026-08-11T14:21:38+08:00")).toBe("14:21:38");
    expect(parseApiDateTime("not-a-date").getTime()).toBeNaN();
  });
});
