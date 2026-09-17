import { getApiBaseUrl } from "@/lib/apiConfig";
import type { ProgramTeamData, ProgramTeamResult } from "@/types/programTeam";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (mirrors `programCommandsApi.ts` / `programDetailApi.ts`'s
 * D-08 split): targets FastAPI directly via `getApiBaseUrl()` and attaches a
 * caller-supplied bearer token. Per ADR-0008, no route hands an access token
 * to client-side JavaScript -- this module must only be imported from a
 * Server Component or a Route Handler, never a `"use client"` module.
 */
export interface FetchProgramTeamOptions {
  range?: string;
  accessToken?: string;
}

/**
 * `GET /api/overview/program-detail/{programId}/team?range=` (PGD-05).
 *
 * `range` is only appended when supplied in `opts` -- omitted otherwise so
 * the backend's own `30d` default applies, matching
 * `fetchProgramCommands`'s optional-range handling.
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise, matching
 * `fetchProgramDetail` / `fetchProgramCommands`. Status mapping: `401` ->
 * `unauthorized` (checked before the generic non-ok branch below, since a
 * bare `!response.ok` check would otherwise swallow it into `error`); any
 * other non-ok response or a network/timeout throw -> `error`.
 *
 * This endpoint never returns 404 for an unknown `program_id` -- it yields
 * `200 {items: []}` instead, matching `fetchProgramCommands`'s D-02
 * precedent. The `ProgramTeamResult` union deliberately omits a `not_found`
 * variant.
 */
export async function fetchProgramTeam(
  programId: string,
  opts?: FetchProgramTeamOptions,
): Promise<ProgramTeamResult> {
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
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}/team${query ? `?${query}` : ""}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 400) {
      return { status: "invalid_range" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ProgramTeamData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
