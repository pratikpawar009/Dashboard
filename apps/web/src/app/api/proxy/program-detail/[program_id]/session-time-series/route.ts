import { NextResponse } from "next/server";

import { fetchProgramSessionSeries } from "@/lib/programSessionSeriesApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/program-detail/[program_id]/session-time-series` -- full
 * server-to-server proxy for `GET
 * /api/overview/program-detail/{program_id}/session-time-series` (ADR-0008),
 * mirroring
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/token-trend/route.ts`
 * exactly. The browser never reaches FastAPI directly: this Route Handler
 * resolves a valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls the
 * server-side `fetchProgramSessionSeries()` (`@/lib/programSessionSeriesApi`)
 * itself -- the access token never enters a JS-reachable scope.
 *
 * `range` and `member_id` are read off the incoming request's query string
 * and forwarded to `fetchProgramSessionSeries()`; either absent forwards as
 * `undefined` (not the literal string `"undefined"`) so the fetcher's own
 * `range: string = "30d"` default applies and `member_id` is omitted from the
 * upstream query rather than sent empty, matching the backend's default
 * behaviour rather than sending a bogus value that would 400.
 *
 * `denied` -> `403 {error:"denied"}` (AF-01, story AC-5): the upstream returns
 * `403` when `member_in_program_visibility` denies a non-self `member_id`, and
 * that denial is passed through as a denial rather than collapsed into
 * `502 upstream_error` -- a permission decision must stay distinguishable from
 * an upstream outage, so a consumer renders "you may not view this member"
 * instead of a retryable failure. Follows the `memberUsage` proxy path's
 * precedent (PGD-05), the only other route that can 403 for this reason.
 *
 * There is no `404` case: an unknown `program_id` returns `200` with an
 * all-zero series upstream (PGD-06-FR-3), so this endpoint has no real 404
 * path and `SessionSeriesResult` carries no `not_found` member.
 *
 * A `401 {error:"session_expired"}` reaching the browser means
 * `callWithAuth()` already exhausted its single retry-after-refresh -- it is
 * a terminal outcome, not an invitation for client-side JS to retry the
 * fetch again.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ program_id: string }> },
): Promise<NextResponse> {
  const { program_id } = await params;
  const { searchParams } = new URL(request.url);
  const range = searchParams.get("range") ?? undefined;
  const memberId = searchParams.get("member_id") ?? undefined;

  try {
    const result = await callWithAuth(
      (accessToken) =>
        fetchProgramSessionSeries(program_id, range, memberId, {
          accessToken,
        }),
      (r) => r.status === "unauthorized",
    );

    switch (result.status) {
      case "ok":
        return NextResponse.json(result.data);
      case "denied":
        return NextResponse.json({ error: "denied" }, { status: 403 });
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
