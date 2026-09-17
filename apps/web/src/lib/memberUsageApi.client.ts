import type { MemberUsageData, MemberUsageResult } from "@/types/memberUsage";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Client-only fetcher for `MemberUsagePopup.tsx` (PGD-05 T-16), mirroring
 * `programTeamApi.client.ts`'s shape: targets the frontend's own same-origin
 * `/api/proxy/personal-usage/[user_id]` Route Handler (T-14), never FastAPI
 * directly -- no `getApiBaseUrl()`, no `Authorization` header, no token
 * concept here (ADR-0008; the proxy resolves and attaches the token
 * server-side).
 *
 * `program_id` travels as a query param on this proxy's incoming request
 * (T-14's own doc comment: "frontend-call-site symmetry"), forwarded by the
 * proxy onto the upstream path segment. `memberId` is the proxy's own
 * `[user_id]` route segment.
 *
 * Status mapping: `403` -> `denied` (AC-11/AC-12 -- distinct from `error`,
 * checked before the generic non-ok branch); `401` -> `unauthorized`
 * (terminal -- this module never retries it); any other non-ok response or a
 * network/timeout throw -> `error`.
 */
export async function fetchMemberUsage(
  programId: string,
  memberId: string,
  range: string,
): Promise<MemberUsageResult> {
  try {
    const response = await fetch(
      `/api/proxy/personal-usage/${memberId}?program_id=${programId}&range=${range}`,
      { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 403) {
      return { status: "denied" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as MemberUsageData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
