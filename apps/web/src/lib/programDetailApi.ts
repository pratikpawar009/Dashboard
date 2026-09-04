import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  ProgramDetailData,
  ProgramDetailResult,
  ProgramSwitcherEntry,
} from "@/types/programDetail";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (D-08): targets FastAPI directly via `getApiBaseUrl()`
 * and attaches a caller-supplied bearer token. Imported by `page.tsx` and,
 * internally, by the two proxy Route Handlers -- never by
 * `ProgramDetailView.tsx` or `programDetailApi.client.ts` (D-08's coupling
 * boundary; the client module has no token to attach and hits the frontend's
 * own same-origin proxy instead).
 *
 * `accessToken` is additive on purpose (DECISIONS.md D-08) -- `switchedFrom`
 * predates it and neither call's signature was renamed to add it.
 */
export interface FetchProgramDetailOptions {
  switchedFrom?: string;
  accessToken?: string;
}

/**
 * `GET /api/overview/program-detail/{programId}` (ADR-0007).
 *
 * Sets `X-Program-Switch-From` only when `opts.switchedFrom` is provided --
 * absent means an initial page load, present means a switcher-triggered
 * reload (DECISIONS.md D-07). Attaches `Authorization: Bearer <token>` only
 * when `opts.accessToken` is present -- the header is omitted, not sent
 * empty, otherwise. Status mapping: `404` -> `not_found`; `401` ->
 * `unauthorized` (checked before the generic non-ok branch below, since a
 * bare `!response.ok` check would otherwise swallow it into `error`); any
 * other non-ok response or a network/timeout throw -> `error`.
 */
export async function fetchProgramDetail(
  programId: string,
  opts?: FetchProgramDetailOptions,
): Promise<ProgramDetailResult> {
  const headers: HeadersInit = {};
  if (opts?.switchedFrom) {
    headers["X-Program-Switch-From"] = opts.switchedFrom;
  }
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ProgramDetailData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}

/**
 * `GET /api/programs` (ADR-0005), for the switch-program selector's option
 * list. Attaches `Authorization: Bearer <token>` only when
 * `opts.accessToken` is present, same rule as `fetchProgramDetail()` above.
 *
 * Returns `[]` on ANY failure, 401 included -- never `unauthorized`. This is
 * intentional, not an oversight: a degraded switcher list is a background,
 * non-critical fetch and must never force a full-page redirect. Do not
 * "fix" this into a 401 signal.
 */
export async function fetchPrograms(opts?: {
  accessToken?: string;
}): Promise<ProgramSwitcherEntry[]> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(`${getApiBaseUrl()}/api/programs`, {
      headers,
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      return [];
    }
    const body = (await response.json()) as {
      programs: ProgramSwitcherEntry[];
    };
    return body.programs;
  } catch {
    return [];
  }
}
