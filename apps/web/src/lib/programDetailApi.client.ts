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
 * Client-only module (D-08): the other half of `programDetailApi.ts`'s
 * split. Its sole consumer is `ProgramDetailView.tsx` (a `"use client"`
 * component). It targets the frontend's own same-origin `/api/proxy/*` Route
 * Handlers, never FastAPI directly -- there is no `getApiBaseUrl()`, no
 * `Authorization` header, no `next/headers`/`tokenStore` import, and no token
 * concept anywhere in this file, because there is no token here to attach:
 * the proxy resolves and attaches it server-side (ADR-0008, D-08/D-09).
 *
 * An `"unauthorized"` result means the proxy already ran
 * `tokenStore.callWithAuth`'s retry-once (D-10) and was still rejected -- it
 * is a terminal outcome. This module must never retry on it; the caller
 * redirects to `/login` instead.
 */
export interface FetchProgramDetailClientOptions {
  switchedFrom?: string;
}

/**
 * `GET /api/proxy/program-detail/{programId}` (ADR-0008).
 *
 * Sets `X-Program-Switch-From` only when `opts.switchedFrom` is provided --
 * absent means an initial mount, present means a switcher-triggered reload
 * (DECISIONS.md D-07), same rule as the server module. Status mapping:
 * `404` -> `not_found`; `401` -> `unauthorized` (checked before the generic
 * non-ok branch below, since a bare `!response.ok` check would otherwise
 * swallow it into `error`); any other non-ok response or a network/timeout
 * throw -> `error`. On `2xx` the body is a bare `ProgramDetailData` -- the
 * proxy unwraps the envelope before responding.
 */
export async function fetchProgramDetail(
  programId: string,
  opts?: FetchProgramDetailClientOptions,
): Promise<ProgramDetailResult> {
  const headers: HeadersInit = {};
  if (opts?.switchedFrom) {
    headers["X-Program-Switch-From"] = opts.switchedFrom;
  }

  try {
    const response = await fetch(`/api/proxy/program-detail/${programId}`, {
      headers,
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

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
 * `GET /api/proxy/programs` (ADR-0008), for the switch-program selector's
 * option list.
 *
 * Returns `[]` on ANY failure, 401 included -- never `unauthorized`. This is
 * the same asymmetry `programDetailApi.ts`'s `fetchPrograms()` carries, and
 * it is intentional here too, not an oversight: the switcher list is a
 * background, non-critical fetch, and degrading it must never trigger the
 * full-page `/login` redirect that an `unauthorized` result causes for
 * `fetchProgramDetail()` above. Do not "fix" this into a 401 signal.
 */
export async function fetchPrograms(): Promise<ProgramSwitcherEntry[]> {
  try {
    const response = await fetch("/api/proxy/programs", {
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
