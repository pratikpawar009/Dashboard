/**
 * Initials derivation from a signed-in user's display name (FR-3).
 *
 * Splits on whitespace and uppercases the first character of the first two
 * tokens (`"Devon Rao"` -> `"DR"`). A single-token name yields that one
 * letter only, no doubling (`"Devon"` -> `"D"`) — this is an assumption, not
 * settled spec: neither the story nor the mockups' static markup covers the
 * single-token case (`docs/stories/SHP-01.md` § Decision log, 2026-09-03).
 *
 * Plain, isolated pure function — no React dependency, no memoization —
 * so it is trivially unit-testable. FR-3 coverage is deliberately deferred
 * per the approved test-case cap (`docs/test-cases/SHP-01.json`
 * `coverage_audit.uncovered`); no dedicated test is added here.
 */
export function deriveInitials(name: string): string {
  const tokens = name.split(/\s+/).filter(Boolean);
  return tokens
    .slice(0, 2)
    .map((token) => token.charAt(0).toUpperCase())
    .join("");
}
