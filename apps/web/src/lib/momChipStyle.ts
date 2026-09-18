import type { CSSProperties } from "react";

/**
 * `mom_direction` → MoM chip `{ color, background }` (OVW-04-NFR-accessibility, D-05).
 *
 * Colors are sourced from `docs/design/tokens.md` § Month-over-month (MoM)
 * chip colors — the single code-side home for these hexes; do not hardcode
 * them elsewhere. The `flat` pair is PO-approved, not mockup-sourced (D-05),
 * but lives in the same token table as `up`/`down` so it isn't a magic
 * number in component code either.
 *
 * Mirrors `getProgramStyle()`'s shape/style discipline (`programStyle.ts`):
 * a plain `React.CSSProperties` object carrying only `color`/`background`,
 * all geometry left to the consuming component's CSS Module.
 *
 * Unlike `getProgramStyle()`'s unrecognized-`type` fallback, a `null`
 * direction here is NOT a display default to paper over — it is FR-3's
 * documented neutral state (fewer than 2 sparkline points). Per DESIGN.md
 * § MoM change indicator, `null` means the chip is omitted entirely, so
 * this returns `null` rather than falling back to any color pair. Callers
 * must treat a `null` result as "render nothing," not as "render a default
 * chip."
 */
export function momChipStyle(
  direction: "up" | "down" | "flat" | null,
): CSSProperties | null {
  if (direction === null) {
    return null;
  }
  const t = MOM_CHIP_COLORS[direction];
  return { color: t.color, background: t.background };
}

const MOM_CHIP_COLORS: Record<
  "up" | "down" | "flat",
  { color: string; background: string }
> = {
  up: { color: "#1f8a5b", background: "#e8f5ee" },
  down: { color: "#d1495b", background: "#fdeaec" },
  flat: { color: "#5b6472", background: "#f0f1f4" },
};
