import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  PersonalSessionsData,
  PersonalSessionsResult,
} from "@/types/personalSessions";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (mirrors `programTeamApi.ts` / `programSessionSeriesApi.ts`'s
 * D-08 split): targets FastAPI directly via `getApiBaseUrl()` and attaches a
 * caller-supplied bearer token. Per ADR-0008, no route hands an access token
 * to client-side JavaScript -- this module must only be imported from a
 * Server Component or a Route Handler, never a `"use client"` module.
 */
export interface FetchPersonalSessionsOptions {
  accessToken?: string;
}

/**
 * `GET /api/personal-usage/{user_id}/sessions?page=&page_size=` (SHP-03).
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise, matching
 * `fetchProgramTeam` / `fetchProgramSessionSeries`. Status mapping: `403` ->
 * `denied` (this route sits behind the same `individual_usage_visibility`
 * self-or-cio gate family the personal-usage routes use -- a denial, not a
 * transient failure, so it must not collapse into `error`); `401` ->
 * `unauthorized` (checked before the generic non-ok branch, since a bare
 * `!response.ok` check would otherwise swallow it into `error`); any other
 * non-ok response or a network/timeout throw -> `error`.
 */
export async function fetchPersonalSessions(
  userId: string,
  page: number,
  pageSize: number,
  opts?: FetchPersonalSessionsOptions,
): Promise<PersonalSessionsResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/personal-usage/${userId}/sessions?${query.toString()}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
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

    const data = (await response.json()) as PersonalSessionsData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
