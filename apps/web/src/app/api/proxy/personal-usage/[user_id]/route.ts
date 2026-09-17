import { NextResponse } from "next/server";

import { getApiBaseUrl } from "@/lib/apiConfig";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait. Matches every other proxy-backing
 * fetcher's `FETCH_TIMEOUT_MS` precedent (`programCommandsApi.ts`,
 * `programTokenTrendApi.ts`).
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Result union for the inlined upstream call below. `denied` (403) is kept
 * distinct from `error` so the route below can map it to its own dedicated
 * response with no data body (AC-12) -- mirrors `meApi.ts`/`overviewApi.ts`'s
 * `forbidden` branch, checked before the generic non-ok fallthrough.
 */
type MemberUsageResult =
  | { status: "ok"; data: unknown }
  | { status: "denied" }
  | { status: "unauthorized" }
  | { status: "error" };

/**
 * `GET /api/proxy/personal-usage/[user_id]` -- full server-to-server proxy
 * for the PGD-05 popup's backend sibling route (ADR-0008, DECISIONS.md
 * D-03/D-04): `GET
 * /api/overview/program-detail/{program_id}/team/{member_id}/usage`, NOT
 * SHP-02's own `GET /api/personal-usage/{user_id}` -- that route enforces the
 * different `individual_usage_visibility` gate (self or cio only), whereas
 * the popup needs `member_in_program_visibility` (self or cio, scoped to a
 * specific program's roster). `[user_id]` in this proxy's own URL segment
 * supplies `member_id` on the upstream path; `program_id` travels as a query
 * param on THIS proxy's incoming request (frontend-call-site symmetry with a
 * possible future direct personal-usage proxy, per PLAN.md's module
 * hierarchy note) and is forwarded onto the upstream path, not the query
 * string.
 *
 * The browser never reaches FastAPI directly: this Route Handler resolves a
 * valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls FastAPI
 * itself -- the access token never enters a JS-reachable scope.
 *
 * `range` is read off the incoming request's query string and forwarded
 * verbatim; an absent `range` param forwards as omitted (not the literal
 * string `"undefined"`) so the backend's own `30d` default applies, matching
 * the token-trend/commands proxies' `range` handling.
 *
 * A missing `program_id` query param is a caller error -- there is no
 * program-scoped gate to evaluate without it, so this proxy 400s before
 * calling upstream at all, rather than forwarding an incomplete URL that
 * FastAPI would 404/422 on for a less legible reason.
 *
 * Status mapping: `200` passes the upstream `PersonalUsageResponse` body
 * through verbatim, no reshaping (AC-10 flows through this proxy layer
 * unchanged). `403` (member_in_program_visibility denial) maps to `403
 * {error:"denied"}` with NO upstream body forwarded (AC-12) -- the denial
 * and any personal-usage field are mutually exclusive by construction, and
 * this proxy must not leak a partial/malformed body on that path either.
 * `401` from `callWithAuth`'s exhausted retry, or a caught
 * `SessionExpiredError`, maps to `401 {error:"session_expired"}` -- a
 * terminal outcome, not an invitation for client-side JS to retry. Any other
 * non-ok response, or a network/timeout throw, maps to `502
 * {error:"upstream_error"}`.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ user_id: string }> },
): Promise<NextResponse> {
  const { user_id: memberId } = await params;
  const { searchParams } = new URL(request.url);
  const programId = searchParams.get("program_id");
  const range = searchParams.get("range") ?? undefined;

  if (!programId) {
    return NextResponse.json({ error: "missing_program_id" }, { status: 400 });
  }

  try {
    const result = await callWithAuth<MemberUsageResult>(
      (accessToken) =>
        fetchMemberUsage(programId, memberId, { range, accessToken }),
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

/**
 * Server-only call to the PGD-05 sibling route (D-03/D-04):
 * `GET /api/overview/program-detail/{program_id}/team/{member_id}/usage?range=`.
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present, matching every other fetcher in this codebase
 * (`fetchProgramCommands`, `fetchProgramTokenTrend`). Status mapping: `403`
 * -> `denied` (checked before the generic non-ok branch, mirroring
 * `meApi.ts`'s `forbidden` check ordering); `401` -> `unauthorized`; any
 * other non-ok response or a network/timeout throw -> `error`.
 */
async function fetchMemberUsage(
  programId: string,
  memberId: string,
  opts: { range?: string; accessToken?: string },
): Promise<MemberUsageResult> {
  const headers: HeadersInit = {};
  if (opts.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  const query = new URLSearchParams();
  if (opts.range !== undefined) {
    query.set("range", opts.range);
  }
  const queryString = query.toString();

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}/team/${memberId}/usage${
        queryString ? `?${queryString}` : ""
      }`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 403) {
      return { status: "denied" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data: unknown = await response.json();
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
