import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  OverviewSummaryData,
  OverviewSummaryResult,
} from "@/types/overview";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (DECISIONS.md D-03): targets FastAPI directly via
 * `getApiBaseUrl()` and attaches a caller-supplied bearer token. Mirrors
 * `programDetailApi.ts::fetchProgramDetail` -- imported only by
 * `app/overview/page.tsx` (T-14), which wraps the call in
 * `tokenStore.callWithAuth()` for the token attach + retry-once-on-401
 * behavior. `AdoptionOverview` (T-13) is a plain component that receives an
 * already-resolved `OverviewSummaryResult` as a prop; it never imports this
 * module or performs its own fetch. No `/api/proxy/*` route exists or is
 * needed for this call (D-03): both regions this story owns are
 * server-rendered on initial load only, with no client-side refetch.
 */
export interface FetchOverviewSummaryOptions {
  accessToken?: string;
}

/**
 * `GET /api/overview/summary` (OVW-01-FR-1/FR-3, DECISIONS.md D-01/D-02).
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise (matches
 * `fetchProgramDetail`'s convention). Status mapping: `403` -> `forbidden`
 * (this endpoint is cio-only, `org_access`, AC-3) checked before `401` ->
 * `unauthorized`, both checked before the generic non-ok branch below, since
 * a bare `!response.ok` check would otherwise swallow either into `error`;
 * any other non-ok response or a network/timeout throw -> `error`.
 */
export async function fetchOverviewSummary(
  opts?: FetchOverviewSummaryOptions,
): Promise<OverviewSummaryResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/overview/summary`, {
      headers,
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

    if (response.status === 403) {
      return { status: "forbidden" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as OverviewSummaryData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
