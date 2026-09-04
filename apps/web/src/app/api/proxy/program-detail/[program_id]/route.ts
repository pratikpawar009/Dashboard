import { NextResponse } from "next/server";

import { fetchProgramDetail } from "@/lib/programDetailApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `GET /api/proxy/program-detail/[program_id]` -- full server-to-server proxy
 * for `GET /api/overview/program-detail/{program_id}` (ADR-0008, DECISIONS.md
 * D-09/D-10). The browser never reaches FastAPI directly: this Route Handler
 * resolves a valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once, AC-7), calls the
 * server-side `fetchProgramDetail()` (`@/lib/programDetailApi`, D-08) itself,
 * and returns a plain `ProgramDetailData` body to the browser -- the access
 * token never enters a JS-reachable scope (ADR-0008's XSS rationale).
 *
 * `X-Program-Switch-From` is read off the incoming request and forwarded
 * verbatim as `opts.switchedFrom` -- this is the one place in this story's
 * code that header still travels anywhere (DECISIONS.md D-11): the hop is
 * server-to-server, so it is never subject to CORS (a browser-enforced
 * mechanism) regardless of what the header's value is.
 *
 * A `401 {error:"session_expired"}` reaching the browser means
 * `callWithAuth()` already exhausted its single retry-after-refresh -- it is
 * a terminal outcome, not an invitation for client-side JS to retry the
 * fetch again (D-10).
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ program_id: string }> },
): Promise<NextResponse> {
  const { program_id } = await params;
  const switchedFrom =
    request.headers.get("X-Program-Switch-From") ?? undefined;

  try {
    const result = await callWithAuth(
      (accessToken) =>
        fetchProgramDetail(program_id, { switchedFrom, accessToken }),
      (r) => r.status === "unauthorized",
    );

    switch (result.status) {
      case "ok":
        return NextResponse.json(result.data);
      case "not_found":
        return NextResponse.json({ error: "not_found" }, { status: 404 });
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
