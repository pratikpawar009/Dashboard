import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  ProgramTokenTrendData,
  ProgramTokenTrendResult,
} from "@/types/programTokenTrend";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (mirrors `programDetailApi.ts`'s D-08 split): targets
 * FastAPI directly via `getApiBaseUrl()` and attaches a caller-supplied
 * bearer token. Never imported by `DailyTokenTrendChart.tsx` or
 * `programTokenTrendApi.client.ts` -- the client module has no token to
 * attach and hits the frontend's own same-origin proxy instead.
 */
export interface FetchProgramTokenTrendOptions {
  accessToken?: string;
}

/**
 * `GET /api/overview/program-detail/{programId}/token-trend?range=` (D-01).
 *
 * `range` defaults to `30d` (AC-1). Attaches `Authorization: Bearer <token>`
 * only when `opts.accessToken` is present -- the header is omitted, not sent
 * empty, otherwise, matching `fetchProgramDetail`. Status mapping: `404` ->
 * `not_found`; `401` -> `unauthorized` (checked before the generic non-ok
 * branch, since a bare `!response.ok` check would otherwise swallow it into
 * `error`); any other non-ok response or a network/timeout throw -> `error`.
 *
 * `tokens`/`period_total`/`avg_per_day` are passed through untouched (D-04)
 * -- this module does not format them.
 */
export async function fetchProgramTokenTrend(
  programId: string,
  range: string = "30d",
  opts?: FetchProgramTokenTrendOptions,
): Promise<ProgramTokenTrendResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}/token-trend?range=${range}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (response.status === 400) {
      return { status: "invalid_range" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ProgramTokenTrendData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
