import { NextResponse } from "next/server";

import { fetchProgramArtifacts } from "@/lib/artifactsApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/artifacts/[program_id]` -- full server-to-server proxy for
 * `GET /api/artifacts/{program_id}` (ADR-0008), mirroring
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/team/route.ts`.
 * The browser never reaches FastAPI directly: this Route Handler resolves a
 * valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls the
 * server-side `fetchProgramArtifacts()` (`@/lib/artifactsApi`) itself -- the
 * access token never enters a JS-reachable scope.
 *
 * Unlike the range-taking Program Detail proxies (token-trend, commands,
 * releases, team, session-time-series), this route takes no query params --
 * there is no `range` to read off the request URL and no `invalid_range`
 * mapping to apply (`ArtifactsResult` carries no such variant; see AF-05 on
 * PGD-06 for why those siblings needed one).
 *
 * `ArtifactsResult` has no `not_found` variant either (T-11) -- this backend
 * route never 404s, an unknown `program_id` returns `200` with an
 * all-zero-count 5-item series instead. No defensive branch is needed here
 * since the union itself excludes it.
 *
 * A `403` from FastAPI (governance_visibility denial) has no dedicated
 * `ArtifactsResult` variant -- it falls through `fetchProgramArtifacts()`'s
 * generic non-ok branch into `{status: "error"}` and is surfaced here as a
 * bare `502 upstream_error` passthrough (no data body), matching this
 * route's existing `error` handling rather than inventing a new status.
 *
 * A `401 {error:"session_expired"}` reaching the browser means
 * `callWithAuth()` already exhausted its single retry-after-refresh -- it is
 * a terminal outcome, not an invitation for client-side JS to retry the
 * fetch again.
 *
 * No caching is applied at this layer -- each request re-invokes
 * `fetchProgramArtifacts()` scoped to the resolved `program_id`, so a viewer
 * of one program can never be served another program's artifact counts.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ program_id: string }> },
): Promise<NextResponse> {
  const { program_id } = await params;

  try {
    const result = await callWithAuth(
      (accessToken) => fetchProgramArtifacts(program_id, { accessToken }),
      (r) => r.status === "unauthorized",
    );

    switch (result.status) {
      case "ok":
        return NextResponse.json(result.data);
      case "unauthorized":
        return NextResponse.json({ error: "session_expired" }, { status: 401 });
      case "error":
        return NextResponse.json({ error: "upstream_error" }, { status: 502 });
    }
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      return NextResponse.json({ error: "session_expired" }, { status: 401 });
    }
    return NextResponse.json({ error: "upstream_error" }, { status: 502 });
  }
}
