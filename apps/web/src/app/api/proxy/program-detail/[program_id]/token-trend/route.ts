import { NextResponse } from "next/server";

import { fetchProgramTokenTrend } from "@/lib/programTokenTrendApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/program-detail/[program_id]/token-trend` -- full
 * server-to-server proxy for `GET
 * /api/overview/program-detail/{program_id}/token-trend` (ADR-0008), mirroring
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/route.ts`. The
 * browser never reaches FastAPI directly: this Route Handler resolves a valid
 * access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls the
 * server-side `fetchProgramTokenTrend()` (`@/lib/programTokenTrendApi`)
 * itself -- the access token never enters a JS-reachable scope.
 *
 * `range` is read off the incoming request's query string and forwarded
 * verbatim to `fetchProgramTokenTrend()`; an absent `range` param forwards as
 * `undefined` (not the literal string `"undefined"`) so `fetchProgramTokenTrend`'s
 * own `range: string = "30d"` default applies, matching the backend's default
 * behaviour rather than sending a bogus value that would 400.
 *
 * `not_found` is handled for `ProgramTokenTrendResult` exhaustiveness (the
 * union it shares with `ProgramDetailResult`), but this endpoint has no real
 * 404 path per REQUIREMENTS.md -- `fetchProgramTokenTrend()` never returns it.
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

  try {
    const result = await callWithAuth(
      (accessToken) =>
        fetchProgramTokenTrend(program_id, range, { accessToken }),
      (r) => r.status === "unauthorized",
    );

    switch (result.status) {
      case "ok":
        return NextResponse.json(result.data);
      case "not_found":
        return NextResponse.json({ error: "not_found" }, { status: 404 });
      case "invalid_range":
        return NextResponse.json({ error: "invalid_range" }, { status: 400 });
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
