import type { ArtifactsData, ArtifactsResult } from "@/types/artifacts";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Client-only module (D-08 pattern, mirrored from
 * `programTeamApi.client.ts`): the client-side counterpart of
 * `artifactsApi.ts`'s server-only `fetchProgramArtifacts()` (T-08). Its
 * consumer is `ArtifactsPanel.tsx` (a `"use client"` component). It targets
 * the frontend's own same-origin `/api/proxy/*` Route Handler, never FastAPI
 * directly -- there is no `getApiBaseUrl()`, no `Authorization` header, no
 * `next/headers`/`tokenStore` import, and no token concept anywhere in this
 * file, because there is no token here to attach: the proxy resolves and
 * attaches it server-side (ADR-0008).
 *
 * An `"unauthorized"` result means the proxy already ran
 * `tokenStore.callWithAuth`'s retry-once and was still rejected -- it is a
 * terminal outcome. This module must never retry on it; the caller redirects
 * to `/login` instead.
 */

/**
 * `GET /api/proxy/artifacts/{programId}` (ADR-0008, T-10).
 *
 * No query params -- unlike sibling `.client.ts` modules, this endpoint takes
 * no `range` (or any other) param, so there is no `invalid_range` mapping to
 * consider here.
 *
 * This route never 404s (`ArtifactsResult` has no `not_found` variant) -- an
 * unknown `program_id` returns `200` with an all-zero-filled `items` array
 * instead (SHP-04-FR-3). Status mapping: `401` -> `unauthorized` (checked
 * before the generic non-ok branch below, since a bare `!response.ok` check
 * would otherwise swallow it into `error`); any other non-ok response or a
 * network/timeout throw -> `error`. On `2xx` the body is a bare
 * `ArtifactsData` -- the proxy unwraps the envelope before responding. Raw
 * integers (`items[].count`) pass through untouched -- no formatting here.
 */
export async function fetchProgramArtifacts(
  programId: string,
): Promise<ArtifactsResult> {
  try {
    const response = await fetch(`/api/proxy/artifacts/${programId}`, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ArtifactsData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
