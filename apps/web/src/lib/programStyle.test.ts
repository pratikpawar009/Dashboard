import { describe, expect, it } from "vitest";

import { getProgramStyle } from "@/lib/programStyle";

/**
 * SHP-01-FR-4 — direct coverage of the `program.type` colour lookup.
 *
 * `ProgramContext.test.tsx` (SHP-01-TC-03) exercises this function only
 * indirectly, through a rendered component, and only for types that exist in
 * `docs/design/tokens.md`. The **unknown-type fallback** — the branch that makes
 * this function fail-soft where `formatPersonaTag` fails loud — had no coverage
 * at all. T-09 was told to flag that gap rather than widen its own scope, so it
 * is closed here instead.
 *
 * Values are asserted against `docs/design/tokens.md` § Program type colors
 * directly (the EMD mockup's `tMap`), not against the function's own output.
 */
describe("getProgramStyle (SHP-01-FR-4)", () => {
  it.each([
    ["Migration", "#2a6fdb", "#eaf1fc"],
    ["Greenfield feature development", "#1f8a5b", "#e8f5ee"],
    ["Brownfield feature development", "#7c5cff", "#efebff"],
    ["Maintenance", "#c08a1e", "#fdf3e0"],
  ])("maps %s to its tokens.md colour pair", (type, color, background) => {
    const { avatarStyle, typeChip } = getProgramStyle(type);
    expect(avatarStyle).toEqual({ color, background });
    // Both keys carry the same pair — the mockup's avatar tile and type chip
    // share one colour source; their geometry differs and lives in CSS (D-06).
    expect(typeChip).toEqual({ color, background });
  });

  // Condition C-3: `program.type` is caller-resolved data, not a shell-owned
  // invariant like `persona`, so an unrecognised value is a display default —
  // NOT the FR-2 fail-loud case. This mirrors the mockup's own lookup,
  // `tMap[P.ptype] || tMap['Migration']`.
  it("falls back to Migration for an unrecognised type instead of throwing", () => {
    const migration = getProgramStyle("Migration");

    for (const unknown of ["infrastructure", "product", "", "MIGRATION"]) {
      expect(() => getProgramStyle(unknown)).not.toThrow();
      expect(getProgramStyle(unknown)).toEqual(migration);
    }
  });

  // The asymmetry with formatPersonaTag is intentional and documented in both
  // files' TSDoc; this locks it so a future "harmonisation" cannot quietly make
  // one of them behave like the other.
  it("never throws, for any input — unlike formatPersonaTag", () => {
    expect(() => getProgramStyle("literally anything")).not.toThrow();
  });

  // REVIEW.md F-3: avatarStyle and typeChip used to be one object aliased into
  // both keys, so a caller mutating either mutated both. Values are equal but
  // the objects must be independent.
  it("returns independent objects for avatarStyle and typeChip", () => {
    const { avatarStyle, typeChip } = getProgramStyle("Migration");

    expect(avatarStyle).toEqual(typeChip);
    expect(avatarStyle).not.toBe(typeChip);

    (avatarStyle as Record<string, string>).color = "#ff0000";
    expect(typeChip).toEqual({ color: "#2a6fdb", background: "#eaf1fc" });
  });

  it("does not leak mutations between separate calls", () => {
    const a = getProgramStyle("Migration");
    (a.avatarStyle as Record<string, string>).color = "#ff0000";

    expect(getProgramStyle("Migration").avatarStyle).toEqual({
      color: "#2a6fdb",
      background: "#eaf1fc",
    });
  });
});
