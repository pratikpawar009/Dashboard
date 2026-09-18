import { getApiBaseUrl } from "@/lib/apiConfig";
import type { ArtifactsData, ArtifactsResult } from "@/types/artifacts";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Server-only module (D-04 split, mirrors `programTeamApi.ts` /
 * `programBoardApi.ts`): targets FastAPI directly via `getApiBaseUrl()` and
 * attaches a caller-supplied bearer token. Per ADR-0008, no route hands an
 * access token to client-side JavaScript -- this module must only be
 * imported from a Server Component or a Route Handler, never a
 * `"use client"` module. Its client-side counterpart is
 * `artifactsApi.client.ts` (T-09).
 */
export interface FetchProgramArtifactsOptions {
  accessToken?: string;
}

/**
 * `GET /api/artifacts/{programId}` (SHP-04-FR-1). No query params -- this
 * route takes none.
 *
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present -- the header is omitted, not sent empty, otherwise, matching
 * `fetchProgramTeam` / `fetchProgramBoard`. Status mapping: `401` ->
 * `unauthorized` (checked before the generic non-ok branch below, since a
 * bare `!response.ok` check would otherwise swallow it into `error`); any
 * other non-ok response or a network/timeout throw -> `error`.
 *
 * This endpoint never returns 404 for an unknown `program_id` -- it yields
 * `200` with an all-zero-count 5-item series instead (SHP-04-AC-3).
 * `ArtifactsResult` deliberately carries no `not_found` variant.
 */
export async function fetchProgramArtifacts(
  programId: string,
  opts?: FetchProgramArtifactsOptions,
): Promise<ArtifactsResult> {
  const headers: HeadersInit = {};
  if (opts?.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/artifacts/${programId}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

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
