/**
 * `member-usage-api` wire shapes (PGD-05 T-16, DESIGN.md § Screen 2).
 *
 * Mirrors backend `PersonalUsageResponse` (`services/api/app/schemas/personal_usage.py`,
 * ADR-0009) verbatim -- the popup's proxy (`/api/proxy/personal-usage/[user_id]`, T-14) forwards
 * this envelope unreshaped. `daily_tokens` is now rendered (DESIGN.md § 2.3 Block 2) via the
 * ADR-0009 amendment (2026-09-17, AF-05 fix): `DailyTokenPoint` gained a raw `tokens: int`
 * alongside its existing pre-formatted `value`, the same computation-input precedent as
 * `CommandEntry.count` below.
 */

/** Mirrors backend `PersonalUsageCard` (5 keys, order-locked, DESIGN.md § 2.3 Block 1). */
export interface MemberUsageCardData {
  glyph: string;
  value: string;
  label: string;
  iconBg: string;
  iconColor: string;
}

/**
 * Mirrors backend `DailyTokenPoint`. `value` is a pre-formatted display string; `tokens` is the
 * same total as a raw int (ADR-0009 amendment, AF-05) -- the field `TokenAreaChart` plots.
 */
export interface MemberDailyTokenPointData {
  date: string;
  value: string;
  tokens: number;
}

/** Mirrors backend `DailyTokenSeries` -- rendered by the popup's Block 2 chart (DESIGN.md § 2.3). */
export interface MemberDailyTokenSeriesData {
  points: MemberDailyTokenPointData[];
  period_total: string;
  avg_per_day: string;
}

/**
 * Mirrors backend `CommandEntry`. `count` is a raw int -- the documented exception to this
 * response's pre-formatted convention (DESIGN.md § 2.3 Block 3 Formatting responsibility);
 * `barStyle` is a ready-to-bind CSS width string, bound directly.
 */
export interface MemberCommandEntryData {
  command: string;
  count: number;
  barStyle: string;
}

/** Mirrors backend `CommandsPanel`. */
export interface MemberCommandsData {
  total_runs: string;
  items: MemberCommandEntryData[];
}

/** Mirrors backend `PersonalUsageResponse` envelope, forwarded verbatim by the T-14 proxy. */
export interface MemberUsageData {
  cards: MemberUsageCardData[];
  daily_tokens: MemberDailyTokenSeriesData;
  commands: MemberCommandsData;
}

/**
 * `fetchMemberUsage()`'s result. `denied` is kept distinct from `error`
 * (AC-11/AC-12, DESIGN.md § 2.5) -- a 403 is a denial, not a transient failure, and the popup
 * renders a structurally different state for each (no retry button on denied).
 */
export type MemberUsageResult =
  | { status: "ok"; data: MemberUsageData }
  | { status: "denied" }
  | { status: "unauthorized" }
  | { status: "error" };
