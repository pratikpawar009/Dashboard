import { getApiBaseUrl } from "@/lib/apiConfig";
import type { MeData, MeResult } from "@/types/me";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (DECISIONS.md D-01): targets FastAPI directly via
 * `getApiBaseUrl()` and attaches a caller-supplied bearer token. Mirrors
 * `overviewApi.ts::fetchOverviewSummary`'s status-mapping and timeout
 * conventions exactly -- imported only by `app/overview/page.tsx` (T-08),
 * which wraps the call in `tokenStore.callWithAuth()` for the token attach +
 * retry-once-on-401 behavior. `AdoptionOverview.tsx` never imports this
 * module or performs its own fetch (OVW-05-FR-3).
 */
export interface FetchMeOptions {
  accessToken?: string;
}

/**
 * `GET /api/me` (AUTH-07, frozen `{name, persona}` shape -- this call site is
 * where research risk #1, stale-docs risk, is put to rest against the live
 * endpoint, not a stub).
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise (matches
 * `fetchOverviewSummary`'s convention). Status mapping: `403` -> `forbidden`
 * (persona resolution failed, README.md `GET /api/me` row) checked before
 * `401` -> `unauthorized`, both checked before the generic non-ok branch
 * below, since a bare `!response.ok` check would otherwise swallow either
 * into `error`; any other non-ok response or a network/timeout throw ->
 * `error`.
 */
export async function fetchMe(opts?: FetchMeOptions): Promise<MeResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/me`, {
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

    const data = (await response.json()) as MeData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
