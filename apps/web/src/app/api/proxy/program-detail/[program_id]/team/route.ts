import { NextResponse } from "next/server";

import { fetchProgramTeam } from "@/lib/programTeamApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/program-detail/[program_id]/team` -- full
 * server-to-server proxy for `GET
 * /api/overview/program-detail/{program_id}/team` (ADR-0008), mirroring
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/commands/route.ts`.
 * The browser never reaches FastAPI directly: this Route Handler resolves a
 * valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls the
 * server-side `fetchProgramTeam()` (`@/lib/programTeamApi`) itself -- the
 * access token never enters a JS-reachable scope.
 *
 * `range` is read off the incoming request's query string and forwarded
 * verbatim to `fetchProgramTeam()`; an absent `range` param forwards as
 * `undefined` (not the literal string `"undefined"`, and not a client-side
 * default) so `fetchProgramTeam`'s own omit-when-undefined behaviour applies
 * and the backend's own `30d` default takes effect, matching the
 * commands/token-trend proxies' `range` handling.
 *
 * `ProgramTeamResult` has no `not_found` variant (T-11) -- this backend route
 * never 404s, an unknown `program_id` returns `200 {items: []}` instead. No
 * defensive branch is needed here since the union itself excludes it.
 *
 * A `401 {error:"session_expired"}` reaching the browser means
 * `callWithAuth()` already exhausted its single retry-after-refresh -- it is
 * a terminal outcome, not an invitation for client-side JS to retry the
 * fetch again.
 *
 * No caching is applied at this layer -- each request re-invokes
 * `fetchProgramTeam()` scoped to the resolved `program_id`, so a viewer of
 * one program can never be served another program's team data.
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
      (accessToken) => fetchProgramTeam(program_id, { range, accessToken }),
      (r) => r.status === "unauthorized",
    );

    switch (result.status) {
      case "ok":
        return NextResponse.json(result.data);
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
