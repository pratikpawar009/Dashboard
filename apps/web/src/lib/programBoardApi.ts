import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  ProgramBoardData,
  ProgramBoardResult,
} from "@/types/programBoard";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module: targets FastAPI directly via `getApiBaseUrl()` and
 * attaches a caller-supplied bearer token. Mirrors
 * `overviewApi.ts::fetchOverviewSummary` verbatim -- no `/api/proxy/*` route
 * exists or is needed for this call, since the Program Board region is
 * server-rendered on initial load only, with no client-side refetch.
 */
export interface FetchProgramBoardOptions {
  accessToken?: string;
}

/**
 * `GET /api/overview/program-board` (OVW-04-FR-1). No query params are sent
 * -- fetches page 1 at the API's default `page_size` (PO resolution #3).
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise (matches
 * `fetchOverviewSummary`'s convention). Status mapping: `403` -> `forbidden`
 * (this endpoint is cio-only, `org_access`, AC-2) checked before `401` ->
 * `unauthorized`, both checked before the generic non-ok branch below, since
 * a bare `!response.ok` check would otherwise swallow either into `error`;
 * any other non-ok response or a network/timeout throw -> `error`.
 */
export async function fetchProgramBoard(
  opts?: FetchProgramBoardOptions,
): Promise<ProgramBoardResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-board`,
      {
        headers,
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      },
    );

    if (response.status === 403) {
      return { status: "forbidden" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ProgramBoardData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
