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
 * Client-only module (D-08 pattern, mirrored from `programDetailApi.client.ts`):
 * the other half of `programTokenTrendApi.ts`'s split. Its consumer is
 * `DailyTokenTrendChart.tsx` (a `"use client"` component) driving the
 * range-toggle (7D/30D/90D) refresh -- AC-5, NFR-002's <=2s budget. It
 * targets the frontend's own same-origin `/api/proxy/*` Route Handler, never
 * FastAPI directly -- there is no `getApiBaseUrl()`, no `Authorization`
 * header, no `next/headers`/`tokenStore` import, and no token concept
 * anywhere in this file, because there is no token here to attach: the
 * proxy resolves and attaches it server-side (ADR-0008).
 *
 * An `"unauthorized"` result means the proxy already ran
 * `tokenStore.callWithAuth`'s retry-once and was still rejected -- it is a
 * terminal outcome. This module must never retry on it; the caller
 * redirects to `/login` instead.
 */

/**
 * `GET /api/proxy/program-detail/{programId}/token-trend?range=` (ADR-0008).
 *
 * `range` drives the toggle; default `30d` (AC-1). Status mapping: `404` ->
 * `not_found`; `401` -> `unauthorized` (checked before the generic non-ok
 * branch below, since a bare `!response.ok` check would otherwise swallow
 * it into `error`); any other non-ok response or a network/timeout throw ->
 * `error`. On `2xx` the body is a bare `ProgramTokenTrendData` -- the proxy
 * unwraps the envelope before responding. Raw integers pass through
 * untouched -- no formatting here (D-04, owned by `DailyTokenTrendChart`).
 */
export async function fetchProgramTokenTrend(
  programId: string,
  range: string,
): Promise<ProgramTokenTrendResult> {
  try {
    const response = await fetch(
      `/api/proxy/program-detail/${programId}/token-trend?range=${range}`,
      { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
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

    const data = (await response.json()) as ProgramTokenTrendData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
