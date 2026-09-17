import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  ProgramCommandsData,
  ProgramCommandsResult,
} from "@/types/programCommands";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only options for `fetchProgramCommands()` (D-04) -- same
 * `accessToken` rule as `programTokenTrendApi.ts`'s own options type. `range`
 * mirrors `fetchProgramReleases`'s optional-range handling.
 */
export interface FetchProgramCommandsOptions {
  range?: string;
  accessToken?: string;
}

/**
 * `GET /api/overview/program-detail/{programId}/commands?range=`
 * (DECISIONS.md D-04). `range` is only appended when supplied in `opts` --
 * omitted otherwise so the backend's own `30d` default applies.
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise, matching
 * `fetchProgramDetail` / `fetchProgramReleases`. Status mapping: `404` ->
 * `not_found`; `401` -> `unauthorized` (checked before the generic non-ok
 * branch below, since a bare `!response.ok` check would otherwise swallow it
 * into `error`); any other non-ok response or a network/timeout throw ->
 * `error`.
 *
 * Unlike `fetchProgramReleases`, this endpoint never actually returns 404
 * (D-02): an unknown or quiet `program_id` yields `200 {total_runs: "0",
 * items: []}`. The `not_found` branch below is kept only for
 * union-exhaustiveness with the shared result shape and defensive handling --
 * it is not an expected outcome for this route.
 */
export async function fetchProgramCommands(
  programId: string,
  opts?: FetchProgramCommandsOptions,
): Promise<ProgramCommandsResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  const params = new URLSearchParams();
  if (opts?.range !== undefined) {
    params.set("range", opts.range);
  }
  const query = params.toString();

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}/commands${query ? `?${query}` : ""}`,
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

    const data = (await response.json()) as ProgramCommandsData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
