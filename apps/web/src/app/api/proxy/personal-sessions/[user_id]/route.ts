import { NextResponse } from "next/server";

import { getApiBaseUrl } from "@/lib/apiConfig";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";
import type { PersonalSessionsResult } from "@/types/personalSessions";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait. Matches every other proxy-backing
 * fetcher's `FETCH_TIMEOUT_MS` precedent (`personal-usage/[user_id]/route.ts`,
 * `programCommandsApi.ts`, `programTokenTrendApi.ts`).
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * `GET /api/proxy/personal-sessions/[user_id]` -- full server-to-server
 * proxy for `GET /api/personal-usage/{user_id}/sessions` (ADR-0008, SHP-03
 * T-12), mirroring
 * `apps/web/src/app/api/proxy/personal-usage/[user_id]/route.ts` exactly:
 * this route has no dedicated `@/lib/*Api.ts` fetcher module in scope
 * (T-12's `files[]` is `route.ts` only -- T-14 adds the client fetch lib
 * separately), so the upstream `fetch()` call is inlined here.
 *
 * The browser never reaches FastAPI directly: this Route Handler resolves a
 * valid access token from the `dashboard_session` cookie via
 * `tokenStore.callWithAuth()` (reactive-401 retry-once) and calls FastAPI
 * itself -- the access token never enters a JS-reachable scope.
 *
 * `page`/`page_size` are read off the incoming request's query string and
 * forwarded verbatim -- the backend (`get_page_params`) owns clamping
 * `page_size` to 100 and defaulting both; this proxy must not re-implement
 * or second-guess that clamp. An absent param forwards as omitted (not the
 * literal string `"undefined"`), matching the `range` forwarding precedent
 * on the sibling proxies above.
 *
 * Status mapping: `200` passes the upstream `PersonalSessionsData` body
 * through verbatim, no reshaping. `403` (RBAC denial,
 * `individual_usage_visibility`: self always, else `cio` only) maps to `403
 * {error:"denied"}` with NO upstream body forwarded -- mirrors the
 * personal-usage proxy's `denied` branch. `401` from `callWithAuth`'s
 * exhausted retry, or a caught `SessionExpiredError`, maps to `401
 * {error:"session_expired"}` -- a terminal outcome, not an invitation for
 * client-side JS to retry. Any other non-ok response, or a network/timeout
 * throw, maps to `502 {error:"upstream_error"}`.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ user_id: string }> },
): Promise<NextResponse> {
  const { user_id } = await params;
  const { searchParams } = new URL(request.url);
  const page = searchParams.get("page") ?? undefined;
  const pageSize = searchParams.get("page_size") ?? undefined;

  try {
    const result = await callWithAuth<PersonalSessionsResult>(
      (accessToken) =>
        fetchPersonalSessions(user_id, { page, pageSize, accessToken }),
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
 * Server-only call to `GET /api/personal-usage/{user_id}/sessions`.
 * Attaches `Authorization: Bearer <token>` only when `opts.accessToken` is
 * present, matching every other fetcher in this codebase
 * (`fetchMemberUsage`, `fetchProgramCommands`, `fetchProgramTokenTrend`).
 * `page`/`page_size` are forwarded verbatim, never re-clamped here (the
 * backend's `get_page_params` owns that). Status mapping: `403` -> `denied`
 * (checked before the generic non-ok branch, mirroring `fetchMemberUsage`'s
 * check ordering); `401` -> `unauthorized`; any other non-ok response or a
 * network/timeout throw -> `error`.
 */
async function fetchPersonalSessions(
  userId: string,
  opts: { page?: string; pageSize?: string; accessToken?: string },
): Promise<PersonalSessionsResult> {
  const headers: HeadersInit = {};
  if (opts.accessToken) {
    headers["Authorization"] = `Bearer ${opts.accessToken}`;
  }

  const query = new URLSearchParams();
  if (opts.page !== undefined) {
    query.set("page", opts.page);
  }
  if (opts.pageSize !== undefined) {
    query.set("page_size", opts.pageSize);
  }
  const queryString = query.toString();

  try {
    const response = await fetch(
      `${getApiBaseUrl()}/api/personal-usage/${userId}/sessions${
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

    const data = await response.json();
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
