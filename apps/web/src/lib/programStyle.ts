import type { CSSProperties } from "react";

/**
 * `program.type` → `{ avatarStyle, typeChip }` color lookup (FR-4, D-04, D-06).
 *
 * Colors are sourced from `docs/design/tokens.md` § Program type colors — the
 * single code-side home for these hexes; do not hardcode them elsewhere.
 *
 * Per D-06 this returns minimal `React.CSSProperties` objects carrying only
 * `color`/`background` — all geometry (size, radius, font, padding) lives in
 * the consuming component's CSS Module, not here. Both keys hold the same
 * `{ color, background }` pair (the mockup's avatar and type-chip share one
 * color source); they stay separate exports because the `persona-shell`
 * contract and the plan name both, and their consumers differ.
 *
 * Unlike `formatPersonaTag()`, an unrecognized `type` does NOT throw — it
 * falls back to the `Migration` entry, matching the mockup's own lookup
 * (`tMap[P.ptype] || tMap['Migration']`). `program.type` is caller-resolved
 * data (research condition C-3), not a shell-owned invariant like `persona`;
 * a mismatch here is a display default, not a fail-loud violation.
 */
export function getProgramStyle(type: string): {
  avatarStyle: CSSProperties;
  typeChip: CSSProperties;
} {
  const t = PROGRAM_TYPE_COLORS[type] ?? PROGRAM_TYPE_COLORS["Migration"];
  // Two distinct objects, not one aliased into both keys (REVIEW.md F-3). The
  // values are identical, so sharing a reference was harmless while both were
  // only ever read — but it made a caller mutating one silently mutate the
  // other, and it would quietly couple them if the avatar and chip ever need
  // to diverge. Cheaper to keep them independent than to rely on nobody writing.
  return {
    avatarStyle: { color: t.color, background: t.background },
    typeChip: { color: t.color, background: t.background },
  };
}

const PROGRAM_TYPE_COLORS: Record<
  string,
  { color: string; background: string }
> = {
  Migration: { color: "#2a6fdb", background: "#eaf1fc" },
  "Greenfield feature development": { color: "#1f8a5b", background: "#e8f5ee" },
  "Brownfield feature development": { color: "#7c5cff", background: "#efebff" },
  Maintenance: { color: "#c08a1e", background: "#fdf3e0" },
};
