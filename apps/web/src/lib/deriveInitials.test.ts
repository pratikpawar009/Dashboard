import { describe, expect, it } from "vitest";

import { deriveInitials } from "@/lib/deriveInitials";

/**
 * SHP-01-FR-3 coverage.
 *
 * `docs/test-cases/SHP-01.json` `coverage_audit.uncovered` deferred FR-3 on the
 * grounds that "initials derivation depends on the same unlanded
 * `signedInUser.name` shape as FR-1". That reasoning holds for FR-1 — whose prop
 * shape really does ride the AUTH-01 session-contract amendment — but not for
 * FR-3: `deriveInitials(name: string)` takes a plain string and is unaffected by
 * how, or under what field name, that string reaches the shell. The function was
 * therefore testable all along, and was the only SHP-01 source file with no
 * direct coverage. FR-1 stays deferred as recorded.
 */
describe("deriveInitials (SHP-01-FR-3)", () => {
  // The four signed-in identities in the decoded ARC/DEV/PMD/EMD mockups —
  // the only real examples the design supplies.
  it.each([
    ["Devon Rao", "DR"],
    ["Maya Chen", "MC"],
    ["Noah Kim", "NK"],
    ["Aisha Bello", "AB"],
  ])("derives %s -> %s (mockup identity bar)", (name, expected) => {
    expect(deriveInitials(name)).toBe(expected);
  });

  it("uses only the first two tokens of a longer name", () => {
    expect(deriveInitials("Ada Augusta Byron Lovelace")).toBe("AA");
  });

  it("uppercases lower-case input", () => {
    expect(deriveInitials("devon rao")).toBe("DR");
  });

  it("collapses whitespace runs rather than emitting empty initials", () => {
    expect(deriveInitials("Devon   Rao")).toBe("DR");
    expect(deriveInitials("\tDevon\tRao ")).toBe("DR");
  });

  // FR-3's logged assumption (docs/stories/SHP-01.md § Decision log,
  // 2026-09-03): a single-token name yields that one letter only, never a
  // doubled "DD". Neither the story nor the mockups' static markup cover this
  // case, so this test is what pins the assumption — if the product decides
  // otherwise, this is the test that should fail and force the conversation.
  it("yields one letter for a single-token name, never doubled (logged assumption)", () => {
    expect(deriveInitials("Devon")).toBe("D");
    expect(deriveInitials("Prince")).toBe("P");
  });

  // Documents CURRENT behaviour for input the spec does not cover — an empty
  // or whitespace-only name yields an empty string rather than throwing. This
  // is deliberately recorded, not endorsed: T-05 was told to raise the
  // empty-input question rather than design for it, and no requirement settles
  // it. A future decision is free to change this and update this expectation.
  it("returns an empty string for empty or whitespace-only input (unspecified; documents current behaviour)", () => {
    expect(deriveInitials("")).toBe("");
    expect(deriveInitials("   ")).toBe("");
  });
});
