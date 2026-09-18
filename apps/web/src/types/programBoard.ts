/**
 * `program-board-api` wire shapes (OVW-04-FR-1). Mirrors
 * `services/api/app/schemas/program_board.py` field-for-field -- the two must
 * not drift.
 */

/**
 * One month's point in a program's token sparkline (OVW-04-FR-1). `tokens` is
 * a raw int -- the frontend renders the mini-chart, matching the token-trend
 * row's raw-int precedent (`README.md` API table).
 */
export interface ProgramBoardSparklinePoint {
  month: string;
  tokens: number;
}

/**
 * Sparkline block for one program board card (OVW-04-FR-1/FR-3).
 * `mom_change_percent`/`mom_direction` are both `null` when fewer than 2
 * points are available; `mom_direction` is otherwise `"up" | "down" | "flat"`.
 */
export interface ProgramBoardSparkline {
  points: ProgramBoardSparklinePoint[];
  mom_change_percent: number | null;
  mom_direction: "up" | "down" | "flat" | null;
}

/**
 * One of the 4 order-locked metric entries per card (ADR-0007 precedent).
 * `glyph`/`label` are fixed presentation constants owned by the producer;
 * `value` is pre-formatted server-side. Order is the contract: total tokens,
 * releases via Harness, features via Harness, active contributors.
 */
export interface ProgramBoardMetric {
  glyph: string;
  label: string;
  value: string;
}

/**
 * One program's card on the program board (OVW-04-FR-1). No
 * `cardStyle`/`avatarStyle`/`typeChip`/`momColor`/`momBg`/`repoBarStyle`
 * fields -- those are all derived client-side (presentation-vs-data
 * boundary). `repos_with_harness_installed`/`repos_total` are raw ints, not a
 * server-composed ratio. `href` is emitted verbatim
 * (`/programs/{program_id}`) -- consumers never reconstruct it.
 */
export interface ProgramBoardCardData {
  program_id: string;
  name: string;
  type: string;
  icon: string;
  description: string;
  href: string;
  sparkline: ProgramBoardSparkline;
  metrics: ProgramBoardMetric[];
  repos_with_harness_installed: number;
  repos_total: number;
}

/**
 * Response envelope for `GET /api/overview/program-board`. Ordered
 * `ORDER BY tokens DESC`; paginated (`page`/`page_size`/`total`), default
 * `page=1, page_size=20`, clamp 100. Empty org falls out naturally as
 * `{items: [], page: 1, page_size: 20, total: 0}`.
 */
export interface ProgramBoardData {
  items: ProgramBoardCardData[];
  page: number;
  page_size: number;
  total: number;
}

/**
 * `fetchProgramBoard()`'s result. Mirrors `OverviewSummaryResult`
 * (`@/types/overview`) -- same `"forbidden"` (403, non-cio) precedence over
 * `"unauthorized"` (401), since this endpoint is gated the same
 * `org_access` way (OVW-04-AC-2).
 */
export type ProgramBoardResult =
  | { status: "ok"; data: ProgramBoardData }
  | { status: "forbidden" }
  | { status: "unauthorized" }
  | { status: "error" };
