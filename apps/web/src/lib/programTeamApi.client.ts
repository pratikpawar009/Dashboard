import type { ProgramTeamData, ProgramTeamResult } from "@/types/programTeam";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Client-only module (D-08 pattern, mirrored from
 * `programTokenTrendApi.client.ts` / `programDetailApi.client.ts`'s
 * `fetchProgramReleases`): the client-side counterpart of
 * `programTeamApi.ts`'s server-only `fetchProgramTeam()` (T-12). Its
 * consumer is `ProgramTeamPanel.tsx` (a `"use client"` component) driving
 * the 7D/30D/90D range toggle. It targets the frontend's own same-origin
 * `/api/proxy/*` Route Handler, never FastAPI directly -- there is no
 * `getApiBaseUrl()`, no `Authorization` header, no `next/headers`/
 * `tokenStore` import, and no token concept anywhere in this file, because
 * there is no token here to attach: the proxy resolves and attaches it
 * server-side (ADR-0008).
 *
 * An `"unauthorized"` result means the proxy already ran
 * `tokenStore.callWithAuth`'s retry-once and was still rejected -- it is a
 * terminal outcome. This module must never retry on it; the caller redirects
 * to `/login` instead.
 */

/**
 * `GET /api/proxy/program-detail/{programId}/team?range=` (ADR-0008, T-13).
 *
 * This route never 404s (`ProgramTeamResult` has no `not_found` variant,
 * T-11) -- an unknown `program_id` returns `200 {items: []}` instead.
 * Status mapping: `401` -> `unauthorized` (checked before the generic
 * non-ok branch below, since a bare `!response.ok` check would otherwise
 * swallow it into `error`); any other non-ok response or a network/timeout
 * throw -> `error`. On `2xx` the body is a bare `ProgramTeamData` -- the
 * proxy unwraps the envelope before responding. Raw integers
 * (`sessions`/`tokens`/`avg_tokens_per_session`) pass through untouched --
 * no formatting here (owned by `ProgramTeamPanel` via `formatTokens`).
 */
export async function fetchProgramTeam(
  programId: string,
  range: string,
): Promise<ProgramTeamResult> {
  try {
    const response = await fetch(
      `/api/proxy/program-detail/${programId}/team?range=${range}`,
      { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

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
