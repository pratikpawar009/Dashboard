/**
 * `session-identity-api` wire shape (AUTH-07, frozen), consumed by
 * `meApi.ts::fetchMe()` (DECISIONS.md D-01, DATA-DESIGN.md § 9 Contract).
 */

/**
 * `GET /api/me`'s response body (AUTH-07) -- **exactly** these two fields.
 * The backend's response model sets `extra="forbid"`, so no `jobTitle` /
 * `email` / `groups` ever exists on the wire to read; `jobTitle` is composed
 * frontend-side only, via `composeSignedInUser.ts` (DECISIONS.md D-03,
 * research condition 1). `name` is `null` for a `/auth/dev-bypass` token,
 * which carries no profile claims (README.md `GET /api/me` row) -- never
 * composed from `email`. `persona` is the resolver's output verbatim, never
 * inferred by a consumer from its own route.
 */
export interface MeData {
  name: string | null;
  persona: string;
}

/**
 * `fetchMe()`'s result (DATA-DESIGN.md § 9 Contract). Mirrors
 * `OverviewSummaryResult`'s (`@/types/overview`) status vocabulary exactly --
 * `"forbidden"` (403, persona resolution failed) checked before
 * `"unauthorized"` (401) in `meApi.ts`, both distinct from the generic
 * `"error"` catch-all (network/timeout throw or any other non-ok status).
 */
export type MeResult =
  | { status: "ok"; data: MeData }
  | { status: "forbidden" }
  | { status: "unauthorized" }
  | { status: "error" };
