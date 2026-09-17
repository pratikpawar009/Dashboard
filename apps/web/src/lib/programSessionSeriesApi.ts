import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  SessionSeriesData,
  SessionSeriesResult,
} from "@/types/programSessionSeries";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (mirrors `programTokenTrendApi.ts`'s D-08 split): targets
 * FastAPI directly via `getApiBaseUrl()` and attaches a caller-supplied
 * bearer token.
 */
export interface FetchProgramSessionSeriesOptions {
  accessToken?: string;
}

/**
 * `GET /api/overview/program-detail/{programId}/session-time-series?range=&member_id=`
 * (PGD-06).
 *
 * `range` defaults to `30d` (AC-1). `memberId`, when provided, is forwarded as
 * `?member_id=` -- the route runs `member_in_program_visibility` before any
 * `session_series` query for a non-self member (FR-6). Attaches
 * `Authorization: Bearer <token>` only when `opts.accessToken` is present --
 * the header is omitted, not sent empty, otherwise, matching
 * `fetchProgramTokenTrend`. Status mapping: `403` -> `denied` (AF-01, story
 * AC-5 -- `member_in_program_visibility` denying a non-self `member_id` is a
 * denial, not a transient failure, so it must not collapse into `error`;
 * follows `fetchMemberUsage`'s precedent, PGD-05); `401` -> `unauthorized`
 * (checked before the generic non-ok branch, since a bare `!response.ok`
 * check would otherwise swallow it into `error`); any other non-ok response
 * or a network/timeout throw -> `error`. There is no `404` case: unknown
 * `program_id` responds `200` with an all-zero series (PGD-06-FR-3).
 *
 * `points[].session_time_seconds`/`period_total_seconds`/`avg_seconds_per_day`
 * are passed through untouched (D-04) -- this module does not format them.
 */
export async function fetchProgramSessionSeries(
  programId: string,
  range: string = "30d",
  memberId?: string,
  opts?: FetchProgramSessionSeriesOptions,
): Promise<SessionSeriesResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  const query = new URLSearchParams({ range });
  if (memberId) {
    query.set("member_id", memberId);
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}/session-time-series?${query.toString()}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 403) {
      return { status: "denied" };
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

    const data = (await response.json()) as SessionSeriesData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
