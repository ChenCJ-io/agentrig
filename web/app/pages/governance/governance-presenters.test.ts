import { describe, expect, it } from "vitest";

import { projectApiPath } from "~/api/governance";

import { governanceSection } from "./governance-page";

describe("governance routing and project scoping", () => {
  it.each([
    ["/production", "production"],
    ["/reviews/open", "reviews"],
    ["/failure-patterns/pattern-1", "failures"],
    ["/jobs", "jobs"],
  ])("maps %s to %s", (pathname, expected) => {
    expect(governanceSection(pathname)).toBe(expected);
  });

  it("encodes project and resource identifiers", () => {
    expect(projectApiPath("team/a", "/production/traces")).toBe(
      "/api/projects/team%2Fa/production/traces",
    );
  });
});
