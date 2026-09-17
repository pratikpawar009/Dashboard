import { NextResponse } from "next/server";

import { fetchProgramCommands } from "@/lib/programCommandsApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/program-detail/[program_id]/commands` -- full
 * server-to-server proxy for `GET
 * /api/overview/program-detail/{program_id}/commands` (ADR-0008, D-04),
 * mirroring
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/token-trend/route.ts`.
 * The browser never reaches FastAPI directly: this Route Handler resolves a
 * valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls the
 * server-side `fetchProgramCommands()` (`@/lib/programCommandsApi`) itself --
 * the access token never enters a JS-reachable scope.
 *
 * `range` is read off the incoming request's query string and forwarded
 * verbatim to `fetchProgramCommands()`; an absent `range` param forwards as
 * `undefined` (not the literal string `"undefined"`, and not a client-side
 * default) so `fetchProgramCommands`'s own omit-when-undefined behaviour
 * applies and the backend's own `30d` default takes effect, matching the
 * token-trend proxy's `range` handling.
 *
 * `not_found` is handled for `ProgramCommandsResult` exhaustiveness, but per
 * decision D-02 this backend route never 404s -- an unknown or quiet
 * `program_id` returns `200 {total_runs: "0", items: []}` instead. This
 * branch is defensive only.
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
      (accessToken) => fetchProgramCommands(program_id, { range, accessToken }),
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
